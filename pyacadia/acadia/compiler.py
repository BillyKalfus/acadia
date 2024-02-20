"""
Assembler for the microarchitecture of the Acadia quantum control system.
"""

__all__ = ["Operable", 
           "Operation", 
           "Symbol", 
           "ManagedResource",
           "ManagedMemory",
           "Processor", 
           "ProcessorSubroutineMixin",
           "Synchronizer"]

import operator
from dataclasses import dataclass, field
from typing import get_type_hints
from abc import ABC, abstractmethod
from itertools import chain

class Operable(type):
    """
    A metaclass used to capture operators acting on instances of derived 
    classes and return a symbolic representation of the operator call.
    """
        
    NUMERIC_OPERATORS = {"eq": operator.eq, 
                         "ne": operator.ne, 
                         "gt": operator.ge, 
                         "lt": operator.lt, 
                         "ge": operator.ge, 
                         "le": operator.le, 
                         "neg": operator.neg, 
                         "abs": operator.abs, 
                         "invert": operator.invert, 
                         "bool": operator.truth,
                         "add": operator.add, 
                         "sub": operator.sub, 
                         "mul": operator.mul, 
                         "floordiv": operator.floordiv, 
                         "truediv": operator.truediv, 
                         "mod": operator.mod, 
                         "pow": operator.pow, 
                         "lshift": operator.lshift, 
                         "rshift": operator.rshift, 
                         "and": operator.and_, 
                         "or": operator.or_, 
                         "xor": operator.xor}
                         
    # MISC_OPERATORS = ["len", "iter", "getitem", "setitem", "call", "contains"]
    
    AUGMENTING_OPERATORS = {"iadd": operator.iadd, 
                            "isub": operator.isub, 
                            "imul": operator.imul, 
                            "ifloordiv": operator.ifloordiv, 
                            "itruediv": operator.itruediv,
                            "imod": operator.imod, 
                            "ipow": operator.ipow, 
                            "ilshift": operator.ilshift, 
                            "irshift": operator.irshift, 
                            "iand": operator.iand, 
                            "ior": operator.ior,
                            "ixor": operator.ixor}
    
    RIGHTHAND_OPERATORS = ["radd", 
                           "rsub", 
                           "rmul", 
                           "rfloordiv", 
                           "rtruediv", 
                           "rmod", 
                           "rpow", 
                           "rlshift", 
                           "rrshift", 
                           "rand", 
                           "ror", 
                           "rxor"]
    
    @staticmethod
    def make_op_func(op_name):
        """
        A function factory for creating functions for operator calls. This is
        mainly necessary because if we try to loop through the list of 
        operators in __new__ like this::

            for op in supported_operators:
                def op_func(*args):
                    return handler(op, *args)
                dct[f"__{op}__"] = op_func

        then the iteration variable ``op`` will be evaluated when ``op_func`` is
        called, instead of when ``op_func`` is defined (you can think of this 
        like referencing a global variable in a function; this is technically
        exactly what's happening, since ``for`` loops in Python don't create a 
        scope). Instead, we want to create a closure that will capture the 
        value of ``op`` at the time of the function definition and appropriately
        return an :class:`Operation` that stores it. See this_ StackOverflow 
        post for more information.

        .. _this: https://stackoverflow.com/questions/3431676/creating-functions-or-lambdas-in-a-loop-or-comprehension
        """

        def op_func(*args):
            if op_name in Operable.AUGMENTING_OPERATORS:                    
                args[0].augmenting_operator_handler(op_name, *(args[1:]))
                return args[0]
            
            if op_name in Operable.RIGHTHAND_OPERATORS:
                return Operation(Operable.NUMERIC_OPERATORS[op_name[1:]], 
                                 *reversed(args))
            
            return Operation(Operable.NUMERIC_OPERATORS[op_name], *args)
                    
        return op_func
    
    @staticmethod
    def make_operator_functions(operators=None):
        funcs = {}
        if operators is not None:
            supported_operators = operators
            
        else:
            supported_operators = chain(Operable.NUMERIC_OPERATORS, 
                                        # Operable.MISC_OPERATORS,
                                        Operable.AUGMENTING_OPERATORS,
                                        Operable.RIGHTHAND_OPERATORS)

        for op in supported_operators:
            funcs[f"__{op}__"] = Operable.make_op_func(op)
                
        return funcs
     
    def __new__(cls, name, bases, dct, operators=None):
        """
        Creates a new :class:`Operable` type.
        
        :param operators: A list of operators that this :class:`Operable` will
            capture. The elements in this list should be the names of the operator
            methods to override, without the underscores.
        :type operators: list of str
        """
        dct.update(Operable.make_operator_functions(operators))
        return super().__new__(cls, name, bases, dct)
    
class Operation(metaclass=Operable):
    """
    A class encapsulating operations to be performed on instances of 
    :class:`Operable` classes. :class:`Operation` objects can also respond to 
    operators in the same manner that produces them (since :class:`Operable` 
    is its metaclass), thereby creating nested :class:`Operation` objects. 
    It is left to the eventual receiver of the :class:`Operation` object to 
    decide whether this is acceptable.
    """

    def __init__(self, op, *args, **kwargs):  
        """
        :param op: An object representing the operation being performed on the 
            provided arguments. This can be any object, since it is up to the eventual 
            receiver of these objects to interpret this field. For example, the eventual 
            receiver may want this to be a callable object that it can directly call 
            on the arguments, or it may want it to be a string that it can interpret, etc.
        :type op: object
        """

        self._op = op
        self._args = args
        self._kwargs = kwargs
        
    def __str__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
    def __repr__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
    def value(self):
        """
        Retrieve the value of the operation acting on its arguments.
        """
        solved_args = []
        for arg in self._args:
            if isinstance(arg, Symbol):
                if not arg.assigned():
                    raise ValueError(f"Attempted to solve `Operation` with"
                                     f" unassigned Symbol: {arg}")
                solved_args.append(arg.value())
            elif isinstance(arg, Operation):
                if not arg.resolveable():
                    raise ValueError(f"Attempted to solve `Operation` with"
                                     f" unresolveable `Operation` as an"
                                     f" argument: {arg}")
                solved_args.append(arg.value())
            else:
                solved_args.append(arg)
        solved_kwargs = {}
        for key,value in self._kwargs.items():
            if isinstance(value, Symbol) or isinstance(value, Operation):
                solved_kwargs[key] = value.value()
            else:
                solved_kwargs[key] = value
                
        return self._op(*solved_args, **solved_kwargs)
    
    def resolveable(self):
        """
        Determine whether all arguments for this :class:`Operation` have
        defined values. For :class:`Symbol` instances, this is when the 
        instance is assigned; for :class:`Operation` instances, this is when
        all of its arguments are resolveable; for all other types, this is 
        assumed to be true.
        
        :rtype: bool
        """
        for arg in chain(self._args, self._kwargs.values()):
            if isinstance(arg, Symbol):
                if not arg.assigned():
                    return False
            elif isinstance(arg, Operation):
                if not arg.resolveable():
                    return False
            
        return True
    
    def augmenting_operator_handler(self, op, *args):
        # Copy all of the information from the augmenting operation
        # The arguments will be (self, <other args>) so we need to make
        # as copy in order not to get a recursive operation
        # Also remove the "i" in front of all the augmenting operator names
        
        clone = Operation(self._op, *self._args, **self._kwargs)
        self._op = Operable.NUMERIC_OPERATORS[op[1:]]
        self._args = (clone, *args)
        self._kwargs = {}
    
class Symbol(metaclass=Operable, operators=Operable.NUMERIC_OPERATORS):
    """
    A symbolic variable with a value not necessarily known at the point of 
    instantiation, but to which a reference should be maintained. A canonical 
    example of an :class:`Operable` class, it allows objects or values to be 
    distributed throughout a program that depend on the future decisions of 
    higher-level entities (e.g., a program translator deciding memory locations
    or array lengths). This requires operator evaluation to be deferred to a 
    future time (and potentially in different ways, depending on the involved 
    objects). In such a situation, this object acts as a placeholder for the 
    desired object.
    """

    def __init__(self, value=None, value_type=None):
        """
        :param value: The value of the :class:`Symbol`\, if known at instantiation. 
            If not provided, may be assigned later.
        :type value: object, optional
        :param value_type: The type of the value, which may be specified when the
            value is not provided.
        """
        if (value is not None
            and value_type is not None 
            and type(value) != value_type):
                
            raise TypeError(f"Conflicting value and type for Symbol; expected"
                            f" type {value_type}, received value of type"
                            f" {type(value)} ({value}).")
        
        self._value = value
        self._assigned = value != None        
        self._value_type = value_type if value_type is not None else type(value)
        
    def __str__(self):
        if isinstance(self._value, int):
            return f"Symbol(assigned={self._assigned}, value=0x{self._value:X})"
        return f"Symbol(assigned={self._assigned}, value={self._value})"
    
    def __repr__(self):
        return str(self)
                
    def assign(self, v, force=False):
        """
        Assigns a value to the :class:`Symbol`\. By default, assignment is only
        supposed to occur once, so an error will be thrown if this is called on
        an already-assigned :class:`Symbol`\. This can be overridden by setting 
        ``force=True``\.
        
        :param v: Value to assign
        :param force: If ``True``\, allows reassignment of already-assigned instances.
        :type force: bool
        """

        if Symbol.assigned(self) and not force:
            raise ValueError("Attempted reassignment of Symbol. If you're sure that this is the correct operation, set argument force=True.")
            
        self._assigned = True
        self._value = v
    
    def value(self):
        if not self.assigned():
            raise ValueError("Attempted access of an unassigned Symbol.")
        return self._value
    
    def value_type(self):
        return self._value_type
    
    def assigned(self):
        if not self._assigned:
            return False
        if isinstance(self._value, Symbol):
            return self._value.assigned()
        if isinstance(self._value, Operation):
            for arg in self._value._args:
                if isinstance(arg, Symbol) and not arg.assigned():
                    return False
            for key,value in self._value._kwargs.items():
                if isinstance(value, Symbol) and not value.assigned():
                    return False
        return True
    
    def operator_handler(self, operation):
        """
        Since :class:`Symbol` objects are considered immutable,
        throw an error if acted upon by an augmenting operator.
        """

        raise ValueError(f"Symbol object {self} acted upon by augmenting"
                         f" operator with operation {operation}.")
        
class ManagedResource(type):
    """
    Metaclass for creating autonomous hardware resource factories. This 
    metaclass implements resource allocation by assigning unique IDs to
    created instances of derived classes (henceforth referred to as resource 
    objects), as well as resource recycling by tracking whether the resource 
    object is released in the future. Its implementation as a metaclass allows
    resource tracking to take place in a class field, which in turn allows 
    multiple identical resource factories to be created and have them each 
    track their own resources without interference simply by subclassing 
    :class:`ManagedResource`\. This also allows the resource objects themselves 
    to be of any type. Additionally, it allows allocation to occur immediately 
    when resource objects are created and potentially return existing resource 
    objects if necessary. This is a subclass of :class:`Operable`\, so that 
    actions on resource objects can be inferred by analyzing produced 
    :class:`Operation` objects.
    """

    def __call__(type_self, *args, **kwargs):
        """
        Creates a new instance of the resource.
        
        :param size: The amount by which the underlying resource ID will be
            increased upon allocation. If not provided, a size of 1 is 
            assumed.
        :type size: int
        :param track: If ``False``, the internal instance tracker does not track
            this instance or advance the allocation index upon creation. This 
            is primarily intended for creating "views" of other resources.
        :type track: bool
        """

        size = kwargs.pop("size", 1)
        if (type_self._allocation_limit is not None 
            and type_self._allocation_index >= type_self._allocation_limit):
            # Find a free instance we can use, as indicated by noting that
            # it is released
            for instance in type_self.instances:
                if instance._released and instance.size >= size:
                    instance._released = False
                    instance.size = size
                    return instance

            raise ValueError(f"Unable to allocate resource;"
                             f" instance limit reached for {type_self} with no"
                             f" released instance found.")
        
        instance = super().__call__(*args, **kwargs)
        instance._released = False
        instance._resource_id = type_self._allocation_index
        instance.size = size
        
        track = kwargs.pop("track", True)
        if track:
            if type_self._next_instance_symbol is not None and not type_self._next_instance_symbol.assigned():
                type_self._next_instance_symbol.assign(instance)            
            type_self.instances.append(instance)
            type_self._allocation_index += instance.size
                
        return instance
    
    def usage(type_self):
        """
        :return: The number of instances created.
        :rtype: int
        """

        return len(type_self.instances)

    def next_instance(type_self):
        """
        :return: A :class:`Symbol` that will be populated with the next instance of
            the resource once generated. 
        """

        if type_self._next_instance_symbol is None or type_self._next_instance_symbol.assigned():
            type_self._next_instance_symbol = Symbol(value_type=type_self)

        return type_self._next_instance_symbol
        
    def __new__(type_self, 
                 type_name, 
                 type_bases, 
                 type_dct, 
                 allocation_limit=None):
        type_instance = super().__new__(type_self, type_name, type_bases, type_dct)
        
        type_instance._allocation_limit = allocation_limit
        type_instance.instances = []
        type_instance._allocation_index = 0
                
        type_self._next_instance_symbol = None
        
        return type_instance
    
class ManagedMemory(ManagedResource):
    """
    A class implementing additional common utilities for managing memory.
    """
    
    def __new__(type_self, 
                 type_name, 
                 type_bases, 
                 type_dct, 
                 memory_size,
                 word_width,
                 base_word_address=None,
                 base_byte_address=None,
                 default_getitem=True):
        """
        Creates a new type of managed memory. The total region of memory
        is comprised of a finite number of entries, referred to as words.
        Words may have arbitrary widths. It is assumed that this memory is 
        shared and that the memory has (possibly disjoint) address mappings 
        in the spaces into which it is mapped. It is assumed that one space
        is word-addressed and the other is byte-addressed, with given offsets
        in both address spaces.
        
        :param memory_size: The total size of the memory region in bytes.
        :type memory_size: int
        :param word_width: Width of a word in bits.
        :type word_width: int
        :param base_word_address: The starting address of the memory region in
            the word-addressed space.
        :param base_byte_address: The starting address of the memory region in
            the byte-addressed space.
        :param default_getitem: If ``True``\, a __getitem__ method will be created
            for the instances of the type. This method will return an 
            :class:`Operation` instance with operation ``getitem`` and with the 
            instance and key as arguments.
        """

        type_instance = super().__new__(type_self, 
                                        type_name, 
                                        type_bases, 
                                        type_dct)
        
        type_instance.memory_size = memory_size
        type_instance.word_width = word_width
        type_instance.base_word_address = base_word_address
        type_instance.base_byte_address = base_byte_address
        
        def res_word_length(self):
            """
            :return: The length of the array in words
            :rtype: int
            """

            width = self.word_width
            l = self.byte_length() * 8 / (width() if callable(width) else width)
            if round(l, 3) != l:
                raise ValueError(f"Non-integer word length ({l}) in array {self}.")
            return int(round(l, 3))

        def res_byte_length(self):
            """
            :return: The length of the array in bytes
            :rtype: int
            """

            return self.size

        def res_word_address(self):
            """
            :return: The address of the array within the word-indexed address 
                space
            :rtype: int
            """

            width = self.word_width
            a = self.base_word_address + (self._resource_id * 8 / (width() if callable(width) else width))
            if round(a, 3) != a:
                raise ValueError(f"Non-integer address ({a}) in array {self}.")
            return int(round(a, 3))

        def res_byte_address(self):
            """
            :return: The address of the array within the byte-indexed address 
                space
            :rtype: int
            """

            return self.base_byte_address + self._resource_id 
        
        def res_view(self, byte_offset=0, byte_length=None):
            """
            Return an untracked ManagedMemory instance providing a view of the
            resource.
            
            :param byte_offset: The offset into the memory where the view starts.
            :type byte_offset: int
            :param byte_length: The length of the view in bytes
            :type byte_length: int
            """
            instance = type_self(size=(byte_length if byte_length is not None else self.size), 
                                 track=False, 
                                 dtype=self._dtype)
            instance._resource_id = self._resource_id + byte_offset
        
        type_instance.word_length = res_word_length
        type_instance.byte_length = res_byte_length
        type_instance.word_address = res_word_address
        type_instance.byte_address = res_byte_address
        type_instance.view = res_view
        type_instance.__len__ = res_word_length

        if default_getitem:
            def res_getitem(self, key):
                return Operation("getitem", self, key)
            type_instance.__getitem__ = res_getitem
        
        return type_instance
    
    def __call__(type_self, *args, **kwargs):
        """
        Create a new instance representing an entry in a pool of managed 
        memory. The ``size`` keyword is understood to represent the amount
        of occupied memory in bytes, and the ``dtype`` argument represents the
        numpy type to which the memory will be cast when attached.
        """
        dtype = kwargs.pop("dtype", None)
        instance = super().__call__(*args, **kwargs)
        instance._dtype = dtype 
        return instance
            
    
@dataclass
class ProcessorInstruction:
    """
    Stores the fields required for an instruction call for a generic processor.
    These fields are as follows:
    
    * ``instruction``\: The name of the instruction to execute, which 
        is used to look up the translation function in the dictionary 
        defining the class' instruction set.

    * ``args``\: Positional arguments provided to the instruction.

    * ``kwargs``\: Keywords arguments provided to the instruction.

    * ``block_start``\: If ``True``\, indicates that this instruction 
    is the first in a non-inlined block.

    * ``block_end``\: If ``True``\, indicates that this instruction is 
    the last in a non-inlined block.

    * ``inline_block_start``\: If ``True``\, indicates that this 
    instruction is the first in an inlined block. This is primarily
    used for bookkeeping and keeping track of indentation.

    * ``inline_block_end``\: If ``True``\, indicates that this 
    instruction is the first in an inlined block. This is primarily
    used for bookkeeping and keeping track of indentation.

    * ``inline_block_level``\: The nesting level of the inline block
    to which this instruction belongs. This is primarily used for 
    bookkeeping and keeping track of indentation. This field is 
    automatically populated during compilation and should not be
    manually manipulated.

    * ``address``\: When this instruction is compiled, it will be assigned
    an address whose value may carry different meanings depending on the
    :class:`Processor` type. This :class:`Symbol` will be automatically 
    populated during compilation and should not be manually manipulated.

    * ``compiled_instructions``\: The output of compiling this
    instruction, which is a list list of any object with an ``assemble``
    method that returns a bytes-like object (or an object that can be 
    converted to bytes). This field is automatically populated during
    compilation and should not be manually manipulated.
    """
    name: str = None
    args: [list, tuple] = None
    kwargs: dict = None
    block_start: bool = False
    block_end: bool = False
    inline_block_start: bool = False 
    inline_block_end: bool = False
    inline_block_level: bool = False
    address: [Symbol, int] = None
    compiled: list = field(default=None, repr=False)
    
    def __post_init__(self):
        # Do basic type-checking
        for field,field_type in get_type_hints(ProcessorInstruction).items(): 
            field_value = getattr(self, field)
            if field_value is not None:
                if isinstance(field_type, list):
                    found = False
                    for t in field_type:
                        if isinstance(field_value, t):
                            found = True
                            break
                    if not found:
                        raise TypeError(f"The type of field {field} must be one of"
                                        f" {field_type}; received {field_value}.")
                elif not isinstance(field_value, field_type):
                    raise TypeError(f"Field {field} must be of type {field_type};"
                                    f" received {field_value}.")
                
        # We'll enforce the name field to be required
        if not self.name:
            raise ValueError("Name field is required.")
            
        # Populate address with a default value if it's not populated,
        # and if it is, enforce it to encapsulate an integer
        if self.address is not None:
            if self.address.value_type() is not int:
                raise TypeError("Address symbols must have `int` as their"
                                f" value type;"
                                f" found {self.address.value_type()}.")
        else:
            self.address = Symbol(value_type=int)
        
class Processor:
    """
    A base class for objects that represent entities capable of being commanded
    by a set of callable instructions. These instructions are defined in 
    subclasses by decorating methods :meth:`Processor.instruction` (see its 
    documentation for a description of its utilization). 

    Instances of :class:`Processor` maintain an internal list of all 
    instructions invoked on it, referred to as the program list. It is 
    understood that the ordering of the program list represents the order in 
    which the hardware will actually execute the instructions contained in it, 
    unless branching occurs. 

    Once a Python script has been written that calls instructions on a 
    :class:`Processor` instance, the instructions need to be translated into 
    native machine code. This can be as simple as taking the fields contained
    in the instructions' arguments and packing them into binary data, but could
    also require inserting additional instructions if the arguments are more 
    complex objects. For example, suppose that a fictitious hardware processor 
    implements an arithmetic logic unit (ALU) that performs mathematical 
    operations on numbers loaded into it from registers, with the result being
    made available to the processor's datapath for later storage into a 
    register. An interface for the corresponding :class:`Processor` class 
    representing this machine might expose a `write_register` instruction which
    directly abstracts the hardware's native instruction for loading a 
    register, but whose arguments can be of type :class:`Operation` in order to
    express the intent to perform a mathematical operation on data and write 
    the result into a register. Although the call to ``write_register`` would be 
    only one entry in the program list, for the hardware to actually carry out 
    the intended action, two additional hardware instructions would first need 
    to be generated to load the data into the ALU (and potentially wait for the
    result to be finished). Only then can the actual register write indicated 
    by the top-level call take place. 
    
    To support this behavior, the process of converting a Python script 
    contains instructions for a :class:`Processor` into a sequence of machine 
    code consists of three distinct steps:

    #. Resource Allocation

        This first step occurs implicitly when the Python code containing 
        the program is executed. When instruction functions are called on 
        :class:`Processor` objects in a script, this creates instances of the 
        class' :class:`Instruction` class which are then stored in the program 
        list. These objects contain metadata about that particular 
        instruction invocation, such as the arguments to the instruction 
        and any resources requested from the :class:`Processor` needed to
        carry out the instruction. Because classes of metaclass 
        :class:`ManagedResource` assign addresses to their instances upon 
        creation, when the script finishes all addressable resources for 
        all processors will have been assigned and allocated. At the end 
        of this stage, the program list will be fully populated and all 
        :class:`Symbol` objects representing automatically-allocated memory
        locations will be assigned.

    #. Compilation

        In this step, each instruction created during symbolic compilation 
        is translated into one or more native instructions and stored in a 
        form more amenable to assembly (which may or may not be the 
        :class:`Instruction` type). Because the functions that the user 
        calls when commanding a :class:`Processor` are directly 
        representative of its native instructions, the primary function 
        of this step is to translate the symbolic arguments passed
        to the instructions and potentially insert additional instructions 
        when needed (such as for expanding compound expressions). At the 
        end of this stage, the `compiled` field of all instructions will be
        populated with data representing the compiled instruction and 
        arguments. While this data is ultimately hardware-specific, it is 
        assumed that the data is in a form that allows it to be directly 
        translated into machine code with no further symbolic solving 
        (except for potentially retrieving the value of an assigned 
        :class:`Symbol`\). The program list will also be rearranged to match
        the desired block structure.

    #. Assembly

        Finally, the data stored as a result of compilation is converted 
        into machine code for the hardware. All :class:`Symbol` objects 
        contained in instructions will be accessed, and simplifications 
        may be performed. 

    In some situations it is desirable to define a distinct block of 
    instructions which are to be executed (potentially conditionally), and
    then have program flow continue from the point immediately following 
    that at which the block was invoked. The compiler must decide where to
    place the instructions comprising the block, with the option of either 
    inserting them at the point at which the block is declared, or placing 
    them in a disjoint region of program memory to which execution is 
    branched when the block is invoked, and returned from when the block is 
    completed.

    A choice between these two methods will depend on whether the block is 
    expected to be executed a majority of the time (or unconditionally); if
    it is, it is more desirable to place the instructions at the point of 
    invocation to avoid the additional latency associated with branching, 
    at the expense of increased program memory usage should the block need 
    to be reused in multiple places. This concept arises in other 
    programming languages when defining subroutines, typically referred to
    as inlining the subroutine. In contrast, if it is expected that the 
    block will typically not be executed (for example, because a condition
    determining its execution will typically not be satisfied), it is 
    preferable to place the block elsewhere so that the majority of the 
    time, execution will simply continue past the conditional branch 
    instruction with no additional latency incurred.

    The ability to dynamically choose between these methods is referred to
    as speculative execution and is a hardware feature of most modern 
    processors (which, rather than deciding where to place instructions, 
    make decisions about the locations in instruction memory from which to
    load the instructions following the branch). Here, we choose to defer 
    this decision to the user.
    
    When writing a program for a system comprised of multiple 
    :class:`Processor` objects, it may become ambiguous which instance a 
    particular command is intended for (especially if there are multiple 
    instances of the same hardware). To prevent the code from becoming 
    unnecessarily verbose, instances of :class:`Processor` can act as context 
    managers. Upon entering the context, the :class:`Processor` instance will
    update a class variable that keeps track of the active processor context.
    External functions that create commands for systems of :class:`Processor`
    objects can then query this variable (using :meth:`active_processor`\) to 
    determine where and how instructions should be generated.
    """
    
    # Keep track of the instruction set of a given type of Processor
    _instruction_set = {}
    
    # Keep track of active processor contexts
    _processor_contexts = []
    
    @classmethod
    def make_instruction_func(cls, name):
        """
        Creates a function that appends a new instruction with the given name 
        to a program list.
        """

        def append_instruction(self, *args, **kwargs):
            instruction_resource = self.Instruction(
                name=name, 
                args=args, 
                kwargs=kwargs, 
                block_start=self._block_start_next, 
                block_end=self._block_end_next,
                inline_block_start=self._inline_block_start_next, 
                inline_block_end=self._inline_block_end_next,
            )

            self._block_start_next = False
            self._block_end_next = False
            self._inline_block_start_next = False
            self._inline_block_end_next = False

            return instruction_resource

        return append_instruction
    
    @classmethod
    def instruction(cls, name=None):
        """
        A decorator for specifying an instruction natively implemented by the
        entity abstracted by this :class:`Processor`\. The decorated method is 
        understood to compile an :class:`Instruction` object (passed as the 
        sole argument) into a list of objects that directly encapsulate a 
        section of machine code for the hardware.  
        
        Functions decorated with this should be instance methods that accept
        (in addition to the ``self`` argument required for all instance methods)
        a single argument, which will be populated with the instruction 
        resource being compiled. The function should populate the instruction
        resource ``compiled_instructions`` when compilation is successful.
        
        Calling a decorated method on a :class:`Processor` instance expresses 
        an intent to command the :class:`Processor` to execute the represented 
        instruction at that point in the program, rather than an intent to 
        compile something. It may be desirable to compile instructions when 
        initially executing the program, but this is not required and therefore
        is considered a distinct step in the compilation process (see the 
        documentation for :meth:`__init__` for further explanation). To 
        implement this behavior, the default instance initializer will iterate 
        through the class instruction set and bind a new method with the name 
        of the decorated function to the instance which, when called, will add 
        an :class:`Instruction` to the program list. Then, when an instance is 
        translating its program list, it can refer to the translation functions
        stored in the class instruction set.
        """
        
        def named_instruction_decorator(compilation_func):
            # We will intentionally return a funtion that does nothing from 
            # this decorator since we don't want to actually create a function
            # for the class, we just want to cache it in the instruction set
            instruction_name = compilation_func.__name__ if name is None else name
            cls._instruction_set[instruction_name] = compilation_func
            return cls.make_instruction_func(instruction_name)
            
        return named_instruction_decorator
    
    def __init__(self):
        """
        Creates an instance with an optional instruction limit.

        :param instruction_limit: Maximum number of instructions allowed to 
            be called on the :class:`Processor`\.
        :type instruction_limit: int, optional
        """
        # A cache for storing arbitrary data and arguments inside the
        # :class:`Processor` for retrieval during assembly
        self._data = None
        
        # A list containing machine instructions for the compiled program
        self._compiled_program = None
        
        # Create some variables that will allow us to keep track of whether the
        # next instruction will start or end a block
        self._block_start_next = False
        self._block_end_next = False
        self._inline_block_start_next = False
        self._inline_block_end_next = False
        
        # The custom resource for storing instructions. One could argue that
        # this should be defined at the class level to better represent the 
        # fact that all processors of a given type will have the same kinds
        # of instructions. The only reason we choose to make the instruction
        # type an instance member is so that its instances created for a 
        # particular Processor object can be tracked
        self.Instruction = ManagedResource(f"{self.__class__.__name__}Instruction", 
                                           (ProcessorInstruction,), 
                                           {})
        
    def __enter__(self):
        Processor._processor_contexts.append(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._processor_contexts.pop()
        
    @classmethod
    def active_processor(cls):
        """
        Get the innermost processor context.

        :return: The :class:`Processor` instance establishing the innermost
            context.
        :rtype: :class:`Processor`
        """

        if len(cls._processor_contexts) == 0:
            return None
            
        return cls._processor_contexts[-1]
            
    def block_start(self, inline=False, previous_instruction=False):
        """
        Indicate that the next instruction called is the first in a
        block. Optionally, this can be applied to the previous instruction by
        setting ``previous_instruction=True``\.

        :param inline: If ``True``\, indicates that the block being created is inline.
        :type inline: bool, optional
        :param previous_instruction: if ``True``\, indicates that the most recent instruction
            added should be the start of the block, rather than the next one to be 
            added.
        :type previous_instruction: bool, optional
        """

        if previous_instruction:
            if inline:
                self.Instruction.instances[-1].inline_block_start = True
            else:
                self.Instruction.instances[-1].block_start = True
        else:
            if inline:
                self._inline_block_start_next = True
            else:
                self._block_start_next = True
            
    def block_end(self, inline=False, next_instruction=False):
        """
        Indicate that the previous instruction called is the last in a 
        block. Optionally, this can be applied to the next 
        instruction by setting ``next_instruction=True``\.

        :param inline: If ``True``\, indicates that the block being created is inline.
        :type inline: bool, optional
        :param next_instruction: if ``True``\, indicates that the next instruction added 
            should be the end of the block, rather than the previous one.
        :type next_instruction: bool, optional
        """

        if next_instruction:
            if inline:
                self._inline_block_end_next = True
            else:
                self._block_end_next = True
        else:
            if inline:
                self.Instruction.instances[-1].inline_block_end = True
            else:
                self.Instruction.instances[-1].block_end = True
        
    def compile_all(self, overwrite=False):
        """
        Compiles the complete program by iterating through the program list and
        calling every instruction's compilation method, while restructuring the
        program to obey the desired block structure. If compilation results
        already exist, ``overwrite`` must be set to ``True`` to overwrite them.

        :param overwrite: If ``True``\, overwrites existing compilation results
        """

        if self._data is not None and not overwrite:
            raise ValueError("Processor data is non-empty; set overwrite=True to overwrite.")
            
        if self._compiled_program is not None and not overwrite:
            raise ValueError("Compiled program is non-empty; set overwrite=True to overwrite.")
            
        # Reset the data dictionary
        self._data = {}
        
        # We'll use a list to keep track of the blocks. The elements of the
        # outermost list correspond to blocks, and these elements are lists.
        # The elements of these block lists are the instructions belonging to
        # the corresponding blocks
        blocks = [[]]
        
        # Keep track of how deep into inline blocks we go (needed to keep track
        # of indentation)
        inline_block_level = [0]
        
        # Some variables for keeping track of program structure as we iterate
        block_prev = None
        block_current = 0
                
        # Compile every instruction and arrange blocks as necessary
        for instruction in self.Instruction.instances:
            
            # Create a new block if necessary
            if instruction.block_start:
                block_prev = block_current
                block_current = len(blocks)
                blocks.append([])
                inline_block_level.append(0)
            
            # Start the inline block, making sure to do this after starting the full block
            if instruction.inline_block_start:
                inline_block_level[block_current] += 1
                
            # Assign the block level
            instruction.inline_block_level = inline_block_level[block_current]
            
            if instruction.compiled is not None and not overwrite:
                raise ValueError("Instruction compilation is non-empty;"
                                 " set overwrite=True to overwrite.")
            
            # Run the actual compilation
            compilation_func = self._instruction_set[instruction.name]
            compilation_func(self, instruction)
            
            # Run some checks before continuing
            if not instruction.compiled:
                raise ValueError(f"Instruction resulted in invalid compilation:"
                                 f" {instruction}")
                
            
            # Add the compilation outputs to the block
            blocks[block_current].append(instruction)
            
            # End the inline block if necessary, making sure to do this before 
            # ending the full block
            if instruction.inline_block_end:
                inline_block_level[block_current] -= 1
            
            # End the block if necessary
            if instruction.block_end:
                block_current = block_prev
                                
        # Flatten the compiled program and assign compiled instruction addresses
        self._compiled_program = []
        for block in blocks:
            for idx_instruction,instruction in enumerate(block):
                instruction.address.assign(len(self._compiled_program))
                self._compiled_program.extend(instruction.compiled)
                
                
    def insert_compiled_instructions(self, index, instructions):
        """
        Inserts instructions into a precompiled program and updates the 
        addresses of all others to reflect the insertion.
        """

        # Iterate in reverse because when we insert an element at a particular 
        # index, the existing element gets bumped forward
        for instruction in reversed(instructions):
            self._compiled_program.insert(index, instruction)
            
        # Update the addresses of Instruction instances (which will automatically
        # be updated for any objects that reference them, including the compiled program)
        for instruction in self.Instruction.instances:
            if instruction.address.value() >= index:
                instruction.address.assign(instruction.address.value() + len(instructions), force=True)
        
    def __eq__(self, other):
        """
        Wrap the `is` operator.
        """
        return self is other
    
class ProcessorSubroutineMixin(ABC):
    """
    A mixin for subclasses of :class:`Processor` for defining subroutines. 
    In this context, a subroutine simply means a named block of instructions; 
    note that this does not necessarily imply that the hardware has the ability
    to branch program execution.
    """

    _subroutines = {}
    
    @classmethod
    def subroutine(cls, func):
        """
        A decorator for creating callable subroutines from Python functions. 
        Because ``__getattr__`` cannot distinguish between method calls and 
        member field accesses, the primary purpose of this decorator is to 
        indicate that when the decorated function is accessed as an attribute 
        of a :class:`Processor` instance, an :class:`Instruction` should be 
        generated that calls the corresponding subroutine (which is stored in 
        the instance). Because of this, when a subroutine is called in the 
        arguments to a function, the :class:`Instruction` created by the 
        subroutine call will be used to populate a new temporary variable, 
        which is then provided to the function.   
        """

        key = func.__name__
        cls._subroutines[key] = func
        cls.instruction(name=key)(cls.call_subroutine)
        def dummy(*args, **kwargs): pass
        return dummy
    
    @abstractmethod
    def call_subroutine(self, instruction_resource):
        """
        A method for compiling a subroutine call. The instruction field of
        the instruction resource will contain the name of the subroutine being
        called.
        """

        pass
    
class Synchronizer:
    """
    A class for orchestrating instructions across processors and implementing 
    synchronization routines. Specific routines are carried out by dedicated 
    subclasses for enforcing different types of synchronization, and an error 
    will be thrown if an instruction is placed into a synchronization block 
    with which it is not compatible.
    
    Instances of :class:`Synchronizer` are context managers and the statements
    within them define the operations to be synchronized in some way. In order
    for an operation to be considered a valid command for a given type of 
    :class:`Synchronizer`\, it must be a function decorated with the 
    :meth:`synchronized` decorator. This decorator wraps the decorated function 
    with logic that stores the call information in the appropriate 
    :class:`Synchronizer`\.
    
    Synchronization is carried out almost entirely by Python dunder methods, so
    following the flow of function calls can be nontrivial. Let's walk through 
    an example to illustrate the interplay between the classes::
    
        class Something:
            def __init__(self):
                self.synchronizer_inst = Synchronizer()

            @Synchronizer.synchronized(some_unique_name, "synchronizer_inst")
            def command(self, *args, **kwargs):
                do_synchronized_things()
    
    The call to :meth:`Synchronizer.synchronized` produces a function decorator
    that will associate calls to ``command`` with the name ``some_unique_name``\. 
    The decorator will then create a new function to replace `command` that 
    will add a record of the function call to the ``synchronizer_inst`` attribute 
    of an instance of ``Something`` when ``command`` is called on it.
    """

    @staticmethod
    def synchronized(name, synchronizer_name):
        """
        Creates a decorator for synchronized function calls. See 
        :class:`Synchronizer` for a detailed description of the interaction
        between this function and instance methods.
        """

        def make(func):
            def synchronized_func(self, *args, **kwargs):
                retval = func(self, *args, **kwargs)
                getattr(self, synchronizer_name).add({"function": name, 
                                                      "self": self,
                                                      "args": args, 
                                                      "kwargs": kwargs,
                                                      "retval": retval})
                return retval
            return synchronized_func
        return make
    
    def __init__(self, allow_standalone=False):
        self._active = False
        self._allow_standalone = allow_standalone

    def __call__(self, **kwargs):
        """
        Configures the :class:`Synchronizer` when the context is being entered.
        """

        self._kwargs = kwargs
        return self
    
    def add(self, obj):        
        if self._active:            
            self._calls.append(obj)
        elif self._allow_standalone:
            self._calls = [obj]
            self.__exit__(None, None, None)
        else:
            raise ValueError("Attempted call to a synchronized function"
                             " outside of a synchronization context.")   
             
    def __enter__(self):
        if self._active:
            raise ValueError("Synchronizer is already active.")
        self._active = True
        self._calls = []
        return self
                
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._active = False
        self._kwargs = {}

        