"""
Assembler for the microarchitecture of the Acadia quantum control system.
"""

__all__ = ["Operable", 
           "Operation", 
           "Symbol", 
           "ManagedResource",
           "ManagedMemory",
           "Processor", 
           "ProcessorSubroutineMixin"]

from types import MethodType
from abc import ABC, abstractmethod
import operator

class Operable(type):
    """
    A metaclass used to capture operators acting on instances of derived 
    classes and return a symbolic representation of the operator call.
    """
    
    # A list of all operator methods that will return an Operation object
    NUMERIC_OPERATORS = ["eq", "ne", "gt", "lt", "ge", "le", 
                 "neg", "abs", "invert", "bool",
                 "add", "radd",  
                 "sub", "rsub", 
                 "mul", "rmul", 
                 "floordiv", "rfloordiv", 
                 "truediv", "rtruediv", 
                 "mod", "rmod", 
                 "pow", "rpow", 
                 "lshift", "rlshift", 
                 "rshift", "rrshift", 
                 "and", "rand", 
                 "or", "ror", 
                 "xor", "rxor"]
                         
    MISC_OPERATORS = ["len", "iter", "getitem", "setitem", "call", "contains"]
    
    # A list of all operators that will require a handler
    HANDLED_OPERATORS = ["iadd", "isub", "imul", "ifloordiv", "itruediv",
                         "imod", "ipow", "ilshift", "irshift", "iand", "ior",
                         "ixor"]
    
    @staticmethod
    def make_op_func(op, handler=None):
        """
        A function factory for creating functions for operator calls. This is
        mainly necessary because if we try to loop through the list of 
        operators in __new__ like this:
        
        ```
        for op in supported_operators:
            def op_func(*args, **kwargs):
                return handler(op, *args, **kwargs)
            dct[f"__{op}__"] = op_func
        ```
        
        then the iteration variable `op` will be evaluated when `op_func` is
        called, instead of when `op_func` is defined (you can think of this 
        like referencing a global variable in a function; this is technically
        exactly what's happening, since `for` loops in Python don't create a 
        scope). Instead, we want to create a closure that will capture the 
        value of `op` at the time of the function definition and appropriately
        return an :class:`Operation` that stores it. See `this StackOverflow 
        post <https://stackoverflow.com/questions/3431676/creating-functions-or-lambdas-in-a-loop-or-comprehension>` 
        for more information.
        """
        def op_func(*args, **kwargs):
            operation = Operation(op, *args, **kwargs)
            if op in Operable.HANDLED_OPERATORS:
                args[0].operator_handler(operation)
                return args[0]
            if handler is not None:
                return handler(operation)
            return operation
        
        return op_func
     
    def __new__(cls, name, bases, dct):
        """
        Creates a new :class:`Operable` type. Certain keyword arguments
        provided to this constructor will augment the behavior of the operator
        methods, listed below as parameters (since they will be parameters of
        the constructor, but will appear as entries in `dct`).
        
        :param operators: A list of operators that this :class:`Operable` will
        capture. The elements in this list should be the names of the operator
        methods to override, without the underscores.
        :type operators: `list` of `str`
        :param operaror_handler: For operators that are understood to modify an object 
        in place (such as +=), the corresponding dunder method will have to 
        return the object itself in order to not overwrite it with the 
        :class:`Operation` object. Therefore, we designate a function as the 
        "augmentation handler" for the :class:`Operable`. When an augmenting
        operator is called on the :class:`Operable`, the augmentation handler
        will be called and passed the newly-created :class:`Operation` as its
        sole argument.
        """
        if "OPERATORS" in dct:
            supported_operators = dct["OPERATORS"]
            
        elif "SUPPORT_HANDLED_OPERATORS" in dct:
            supported_operators = (Operable.NUMERIC_OPERATORS 
                                   + Operable.MISC_OPERATORS)
            if dct["SUPPORT_HANDLED_OPERATORS"]:
                supported_operators += Operable.HANDLED_OPERATORS
        else:
            supported_operators = (Operable.NUMERIC_OPERATORS 
                                   + Operable.MISC_OPERATORS 
                                   + Operable.HANDLED_OPERATORS)
            
        handlers = dct["handlers"] if "handlers" in dct else []
            
        for op in supported_operators:
            if op in handlers:
                dct[f"__{op}__"] = Operable.make_op_func(op, handler=handlers[op])
            else:
                dct[f"__{op}__"] = Operable.make_op_func(op)
                
        return super(Operable, cls).__new__(cls, name, bases, dct)
    
class Operation(metaclass=Operable):
    """
    A class encapsulating operations to be performed on instances of 
    :class:`Operable` classes. :class:`Operation` objects can also respond to 
    operators in the same manner that produces them (since :class:`Operable` 
    is its metaclass), thereby creating nested :class:`Operation` objects. 
    It is left to the eventual receiver of the :class:`Operation` object to 
    decide whether this is acceptable.
    
    :param op: An object representing the operation being performed on the 
    provided arguments. This can be any object, since it is up to the eventual 
    receiver of these objects to interpret this field. For example, the eventual 
    receiver may want this to be a callable object that it can directly call 
    on the arguments, or it may want it to be a string that it can interpret, etc.
    
    :type op: object
    
    :param operator_handler: A function to be called when the :class:`Operation`
    is acted on with an augmenting operator (e.g., +=). 
    """
    def __init__(self, op, *args, **kwargs):  
        self._op = op
        self._args = args
        self._kwargs = kwargs
        
    def __str__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
    def __repr__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
    def value(self, op_lib=operator):
        solved_args = []
        for arg in self._args:
            if isinstance(arg, Symbol) or isinstance(arg, Operation):
                solved_args.append(arg.value())
            else:
                solved_args.append(arg)
        solved_kwargs = {}
        for key,value in self._kwargs.items():
            if isinstance(arg, Symbol) or isinstance(arg, Operation):
                solved_kwargs[key] = value.value()
            else:
                solved_kwargs[key] = value
                
        return getattr(op_lib, self._op)(*solved_args, **solved_kwargs)
    
    def operator_handler(self, operation):
        """
        Since operations do not support augmentation, throw an error if acted
        upon by an augmenting operator.
        """
        raise ValueError(f"Operation object {self} acted upon by augmenting"
                         f" operator with operation {operation}.")
    
class Symbol(metaclass=Operable):
    """
    A symbolic variable with a value not necessarily known to the user but 
    guaranteed to be available at the time of translation. A canonical example 
    of an :class:`Operable` class, it allows objects or values to be 
    distributed throughout a program that depend on the future decisions of 
    higher-level entities (e.g., a program translator deciding memory locations
    or array lengths). This requires operator evaluation to be deferred to a 
    future time (and potentially in different ways, depending on the involved 
    objects). In such a situation, this object acts as a placeholder for the 
    desired object.
    
    :param value: The value of the :class:`Symbol`, if known at instantiation. 
    If not provided, may be assigned later.
    
    :type value: object, optional
    
    :param value_type: The type of the value, which may be specified when the
    value is not provided.
    """
    def __init__(self, value=None, value_type=None):
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
        Assigns a value to the :class:`Symbol`. By default, assignment is only
        supposed to occur once, so an error will be thrown if this is called on
        an already-assigned :class:`Symbol`. This can be overridden by setting 
        `force=True`.
        
        :param v: Value to assign
        
        :param force: If `True`, allows reassignment of already-assigned instances.
        
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
        
class ManagedResource(Operable):
    """
    Metaclass for creating autonomous hardware resource factories. This 
    metaclass implements resource allocation by assigning unique IDs to
    created instances of derived classes (henceforth referred to as "resource 
    objects"), as well as resource recycling by tracking whether the resource 
    object is released in the future. Its implementation as a metaclass allows
    resource tracking to take place in a class field, which in turn allows 
    multiple identical resource factories to be created and have them each 
    track their own resources without interference simply by subclassing 
    :class:`ManagedResource`. This also allows the resource objects themselves 
    to be of any type. Additionally, it allows allocation to occur immediately 
    when resource objects are created and potentially return existing resource 
    objects if necessary. This is a subclass of :class:`Operable`, so that 
    actions on resource objects can be inferred by analyzing produced 
    :class:`Operation` objects.
    
    :param instance_limit: The maximum number of instances that may be 
    created by the class.
    :type instance_limit: int, optional
    :param required_parameters: A list of parameters which must be supplied to
    instances' initializers. The supplied values are assigned to the instance
    as attributes.
    :type required_parameters: list of str, optional
    :param use_instance_size: If `True`, indicates that the allocation 
    offset should be increased by an amount equal to the provided `size` 
    keyword.
    :type use_instance_size: bool, optional
    """
    def __new__(
        cls_meta_new,
        name_meta_new,
        bases_meta_new,
        dct_meta_new,
        allocation_limit=None,
        required_parameters=None,
        use_instance_size=False):
        
        def cls_new(cls, *inst_args, **inst_kwargs):
            """
            Create a new instance representing a hardware resource. If a 
            resource limit has been provided and reached, existing 
            allocations will be checked to see if they were released, and if so,
            may be returned.
            
            :param resource_id: The ID of resource, which may be any type and 
            whose interpretation is left to the owning class. If not provided,
            a new :class:`Symbol` will be instantiated.
            """
            if (allocation_limit is not None 
                and cls._allocation_index >= allocation_limit):
                # Find a free instance we can use, as indicated by noting that
                # it is released
                for instance in cls.instances:
                    if instance._released:
                        instance._released = False
                        return instance
                    
                raise ValueError(f"Unable to allocate resource;"
                                 f" instance limit reached for {cls} with no"
                                 f" released instance found.")
            
            instance = super(cls, cls).__new__(cls)
            instance._released = False
            instance._resource_id = cls._allocation_index
            
            if required_parameters is not None:
                for param in required_parameters:
                    if param not in inst_kwargs:
                        raise ValueError(f"{name_meta_new} instances must be"
                                         f" instantiated with parameter `{param}`.")
                    setattr(instance, param, inst_kwargs[param])
            
            instance._size = inst_kwargs["size"] if "size" in inst_kwargs and use_instance_size else 1
            
            if hasattr(cls, "_next_instance_symbol") and not cls.next_instance_assigned():
                cls._next_instance_symbol.assign(instance)            
            cls.instances.append(instance)
            cls._allocation_index += instance._size
            
            return instance
        
        def usage(cls):
            """
            :return: The number of instances created.
            :rtype: int
            """
            return len(cls.instances)
        
        def next_instance(cls):
            """
            :return: A :class:`Symbol` that will be populated with the next instance of
            the resource once generated. 
            """
            if not hasattr(cls, "_next_instance_symbol") or cls.next_instance_assigned():
                cls._next_instance_symbol = Symbol(value_type=cls)
            
            return cls._next_instance_symbol
        
        def next_instance_assigned(cls):
            """
            :return: A :class:`Symbol` that will be populated with the next instance of
            the resource once generated. 
            """
            if not hasattr(cls, "_next_instance_symbol"):
                return False
            
            return cls._next_instance_symbol.assigned()
        
        attrs = {"instances": [],
                 "__new__": cls_new,
                 "_allocation_index": 0,
                 "next_instance": classmethod(next_instance),
                 "next_instance_assigned": classmethod(next_instance_assigned),
                 "usage": classmethod(usage),
                **dct_meta_new}

        new_cls = super().__new__(cls_meta_new, name_meta_new, bases_meta_new, attrs)
        return new_cls
    
class ManagedMemory(ManagedResource):
    """
    A class implementing additional common utilities for managing memory.
    """
    
    def __new__(cls_meta_new,
                name_meta_new,
                bases_meta_new,
                dct_meta_new,
                pool_size,
                word_width,
                required_parameters=None,
                base_word_address=None,
                base_byte_address=None,
                getitem_handler=None,
                setitem_handler=None):
        """
        Creates a new type of managed memory. The total region of memory
        (also referred to as the "pool") is comprised of a finite number of 
        entries, referred to as "words". Words may have arbitrary widths.
        It is assumed that this memory is shared and that the memory has 
        (possibly disjoint) address mappings in the spaces into which it is
        mapped. It is assumed that one space is word-addressed and the other
        is byte-addressed, with given offsets in both address spaces.
        
        :param pool_size: The total size of the memory region in number of 
        words.
        :type pool_size: int
        :param word_width: Width of a word in the memory pool.
        :type word_width: int
        :param base_word_address: The starting address of the memory region in
        the word-addressed space.
        :param base_byte_address: The starting address of the memory region in
        the byte-addressed space.
        :param getitem_handler: A function to be called with an instance of 
        :class:`Operation` when `getitem` is invoked on the resource instance.
        :type getitem_handler: callable
        :param setitem_handler: A function to be called with an instance of 
        :class:`Operation` when `setitem` is invoked on the resource instance.
        :type setitem_handler: callable
        """
        
        def res_word_length(self):
            """
            :return: The length of the array in words
            :rtype int:
            """
            return self._size
        
        def res_byte_length(self):
            """
            :return: The length of the array in bytes
            :rtype: int
            """
            return self.word_length() * (word_width // 8)
        
        def res_word_address(self):
            """
            :return: The address of the array within the word-indexed address 
            space
            :rtype: int
            """
            return base_word_address + self._resource_id
        
        def res_byte_address(self):
            """
            :return: The address of the array within the byte-indexed address 
            space
            :rtype: int
            """
            return base_byte_address + (self._resource_id * (word_width // 8))
        
        # Add the new address methods                
        dct_meta_new["word_address"] = res_word_address
        dct_meta_new["byte_address"] = res_byte_address
        dct_meta_new["word_length"] = res_word_length
        dct_meta_new["byte_length"] = res_byte_length
        
        # The "default" address will be the word address
        dct_meta_new["address"] = res_word_address 
        
        # Add the handlers for getitem and setitem
        operators = dct_meta_new["OPERATORS"] if "OPERATORS" in dct_meta_new else []
        handlers = dct_meta_new["handlers"] if "handlers" in dct_meta_new else {}
        
        if getitem_handler is not None:
            if "getitem" not in operators:
                operators.append("getitem")
            if "getitem" not in handlers:
                handlers["getitem"] = getitem_handler
                
        if setitem_handler is not None:    
            if "setitem" not in operators:
                operators.append("setitem")
            if "getitem" not in handlers:
                handlers["getitem"] = setitem_handler    
                
        dct_meta_new["OPERATORS"] = operators
        dct_meta_new["handlers"] = handlers
        
        # Store some parameters
        dct_meta_new["pool_size"] = pool_size
        dct_meta_new["word_width"] = word_width
        dct_meta_new["required_parameters"] = required_parameters
        dct_meta_new["base_word_address"] = base_word_address
        dct_meta_new["base_byte_address"] = base_byte_address
        
        return super().__new__(cls_meta_new,
                                name_meta_new,
                                bases_meta_new,
                                dct_meta_new,
                                use_instance_size=True,
                                required_parameters=required_parameters,
                                allocation_limit=pool_size)
        
class Processor(ABC):
    """
    A base class for objects that represent entities capable of being commanded
    by a set of callable "instructions". These instructions are defined in 
    subclasses by decorating methods :meth:`Processor.instruction` (see its 
    documentation for a description of its utilization). 

    Instances of :class:`Processor` maintain an internal list of all 
    instructions invoked on it, referred to as the "program list". It is 
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
    the result into a register. Although the call to `write_register` would be 
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
        end of this stage, the "compiled" field of all instructions will be
        populated with data representing the compiled instruction and 
        arguments. While this data is ultimately hardware-specific, it is 
        assumed that the data is in a form that allows it to be directly 
        translated into machine code with no further symbolic solving 
        (except for potentially retrieving the value of an assigned 
        :class:`Symbol`). The program list will also be rearranged to match
        the desired block structure.

    #. Assembly

        Finally, the data stored as a result of compilation is converted 
        into machine code for the hardware. All :class:`Symbol` objects 
        contained in instructions will be accessed, and simplifications 
        may be performed. 

    In some situations it is desirable to define a distinct "block" of 
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
    as "inlining" the subroutine. In contrast, if it is expected that the 
    block will typically not be executed (for example, because a condition
    determining its execution will typically not be satisfied), it is 
    preferable to place the block elsewhere so that the majority of the 
    time, execution will simply continue past the conditional branch 
    instruction with no additional latency incurred.

    The ability to dynamically choose between these methods is referred to
    as "speculative execution" and is a hardware feature of most modern 
    processors (which, rather than deciding where to place instructions, 
    make decisions about the locations in instruction memory from which to
    load the instructions following the branch). Here, we choose to defer 
    this decision to the user.
    """
    
    _instruction_set = {}
    
    @classmethod
    def make_instruction_func(cls, name):
        """
        Creates a function that appends an instruction dictionary to a 
        program list. The `dict` encapsulated by the 
        :class:`ManagedResource` contains a few dedicated fields:

        * `instruction`: The name of the instruction to execute, which 
        is used to look up the translation function in the dictionary 
        defining the class' instruction set.

        * `args`: Positional arguments provided to the instruction.

        * `kwargs`: Keywords arguments provided to the instruction.

        * `block_start`: If `True`, indicates that this instruction 
        is the first in a non-inlined block.

        * `block_end`: If `True`, indicates that this instruction is 
        the last in a non-inlined block.

        * `inline_block_start`: If `True`, indicates that this 
        instruction is the first in an inlined block. This is primarily
        used for bookkeeping and keeping track of indentation.

        * `inline_block_end`: If `True`, indicates that this 
        instruction is the first in an inlined block. This is primarily
        used for bookkeeping and keeping track of indentation.

        * `inline_block_level`: The nesting level of the inline block
        to which this instruction belongs. This is primarily used for 
        bookkeeping and keeping track of indentation. This field is 
        automatically populated during compilation and should not be
        manually manipulated.

        * `compiled_address`: When this instruction is compiled, it 
        will result in one or more native instructions in the resulting
        flattened program list. The value of this field is the 
        index within this list of the first new entry produced by this 
        instruction. This field is automatically populated during 
        compilation and should not be manually manipulated.

        * `compiled_instructions`: The output of compiling this
        instruction. This field is automatically populated during
        compilation and should not be manually manipulated.

        """
        def append_instruction(self, *args, **kwargs):
            instruction_resource = self._Instruction({
                "instruction": name, 
                "args": args, 
                "kwargs": kwargs, 
                "block_start": self._block_start_next, 
                "block_end": self._block_end_next,
                "inline_block_start": self._inline_block_start_next, 
                "inline_block_end": self._inline_block_end_next,
                "inline_block_level": None,
                "compiled_address": Symbol(value_type=int),
                "compiled_instructions": None,
            })

            self._block_start_next = False
            self._block_end_next = False
            self._inline_block_start_next = False
            self._inline_block_end_next = False

            return instruction_resource

        return append_instruction
    
    @classmethod
    def instruction(cls, name=None):
        """
        A decorator for specifying an instruction "natively" implemented by the
        entity abstracted by this :class:`Processor`. The decorated method is 
        understood to compile an :class:`Instruction` object (passed as the 
        sole argument) into a list of objects that directly encapsulate a 
        section of machine code for the hardware.  
        
        Functions decorated with this should be instance methods that accept
        (in addition to the `self` argument required for all instance methods)
        a single argument, which will be populated with the instruction 
        resource being compiled. The function should populate the instruction
        resource `"compiled_instructions"` when compilation is successful.
        
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
        be called on the :class:`Processor`.
        
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
        def instruction_address(instruction_self):
            return instruction_self["compiled_address"]
        
        self._Instruction = ManagedResource(
                                f"Instruction", 
                                (dict,), 
                                {"OPERATORS": [],
                                 "address": instruction_address})
            
    def block_start(self, inline=False, previous_instruction=False):
        """
        Indicate that the next instruction called is the first in a
        block. Optionally, this can be applied to the previous instruction by
        setting `previous_instruction=True`.
        :param inline: If `True`, indicates that the block being created is inline.
        :type inline: `bool`, optional
        :param previous_instruction: if `True`, indicates that the most recent instruction
        added should be the start of the block, rather than the next one to be 
        added.
        :type previous_instruction: `bool`, optional
        """
        if previous_instruction:
            self._Instruction.instances[-1]["inline_block_start" if inline else "block_start"] = True
        else:
            if inline:
                self._inline_block_start_next = True
            else:
                self._block_start_next = True
            
    def block_end(self, inline=False, next_instruction=False):
        """
        Indicate that the previous instruction called is the last in a 
        block. Optionally, this can be applied to the next 
        instruction by setting `next_instruction=True`.
        :param inline: If `True`, indicates that the block being created is inline.
        :type inline: `bool`, optional
        :param next_instruction: if `True`, indicates that the next instruction added 
        should be the end of the block, rather than the previous one.
        :type next_instruction: `bool`, optional
        """
        if next_instruction:
            if inline:
                self._inline_block_end_next = True
            else:
                self._block_end_next = True
        else:
            self._Instruction.instances[-1]["inline_block_end" if inline else "block_end"] = True
        
    def compile_all(self, overwrite=False):
        """
        Compiles the complete program by iterating through the program list and
        calling every instruction's compilation method, while restructuring the
        program to obey the desired block structure. If compilation results
        already exist, `overwrite` must be set to `True` to overwrite them.
        :param overwrite: If `True`, overwrites existing compilation results
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
        for instruction in self._Instruction.instances:
            compilation_func = self._instruction_set[instruction["instruction"]]
            
            # Create a new block if necessary
            if instruction["block_start"]:
                block_prev = block_current
                block_current = len(blocks)
                blocks.append([])
                inline_block_level.append(0)
            
            # Start the inline block, making sure to do this after starting the full block
            if instruction["inline_block_start"]:
                inline_block_level[block_current] += 1
                
            # Assign the block level
            instruction["inline_block_level"] = inline_block_level[block_current]
            
            if instruction["compiled_instructions"] and not overwrite:
                raise ValueError("Instruction compilation is non-empty;"
                                 " set overwrite=True to overwrite.")
            
            # Run the actual compilation
            compilation_func(self, instruction)
            
            # Run some checks before continuing
            if len(instruction["compiled_instructions"]) == 0:
                raise ValueError(f"Instruction resulted in empty compilation:"
                                 f" {instruction}")
                
            
            # Add the compilation outputs to the block
            blocks[block_current].append(instruction)
            
            # End the inline block if necessary, making sure to do this before 
            # ending the full block
            if instruction["inline_block_end"]:
                inline_block_level[block_current] -= 1
            
            # End the block if necessary
            if instruction["block_end"]:
                block_current = block_prev
                                
        # Flatten the compiled program and assign compiled instruction addresses
        self._compiled_program = []
        for block in blocks:
            for idx_instruction,instruction in enumerate(block):
                instruction["compiled_address"].assign(len(self._compiled_program))
                self._compiled_program.extend(instruction["compiled_instructions"])
                                    
    def assemble(self):
        """
        Assembles a complete program into machine code appropriate for the 
        hardware executing the program.
        """
        return [instr.assemble() for instr in self._compiled_program]
    
class ProcessorSubroutineMixin(ABC):
    """
    A mixin for subclasses of :class:`Processor` for defining subroutines. 
    In this context, a "subroutine" simply means a named block of instructions; 
    note that this does not necessarily imply that the hardware has the ability
    to branch program execution.
    """
    _subroutines = {}
    
    @classmethod
    def subroutine(cls, func):
        """
        A decorator for creating callable subroutines from Python functions. 
        Because `__getattr__` cannot distinguish between method calls and 
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
    
    @classmethod
    @abstractmethod
    def call_subroutine(self, instruction_resource):
        """
        A method for compiling a subroutine call. The "instruction" field of
        the instruction resource will contain the name of the subroutine being
        called.
        """
        pass
    