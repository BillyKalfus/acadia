"""
A set of classes defining the interface for abstractions of hardware
processors.
"""

__all__ = ["Processor", 
           "ProcessorSubroutineMixin", 
           "PythonProcessor"]

from numbers import Number
from abc import ABC, abstractmethod
from types import MethodType, FunctionType
from contextlib import contextmanager
import operator

from .assembler import Operation, Symbol, ManagedResource

class Processor(ABC):
    """
    A base class for objects that represent entities capable of being commanded
    by a set of native "instructions". Native instructions are defined in 
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
    def instruction(cls, name=None):
        """
        A decorator for specifying an instruction "natively" implemented by the
        entity abstracted by this :class:`Processor`. The decorated method is 
        understood to compile an :class:`Instruction` object (passed as the 
        sole argument) into a list of objects that directly encapsulate a 
        section of machine code for the hardware.  
        
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
            key = compilation_func.__name__ if name is None else name
            cls._instruction_set[key] = compilation_func
            def dummy(*args, **kwargs): pass
            return dummy
            
        return named_instruction_decorator
    
    def __init__(self, instruction_limit=None):
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
        self._Instruction = ManagedResource(
                                f"Instruction", 
                                (dict,), 
                                {"OPERATORS": []}, 
                                instance_limit=instruction_limit)
        
        # For every instruction, bind a new method to the instance with the name
        # of the instruction
        for instruction_name,translator in self._instruction_set.items():
            def append_instruction(proc_self, *args, **kwargs):
                """
                Append an instruction to a program list. The `dict` 
                encapsulated by the :class:`ManagedResource` contains a few
                dedicated fields:
                
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
                instruction_resource = proc_self._Instruction({
                    "instruction": instruction_name, 
                    "args": args, 
                    "kwargs": kwargs, 
                    "block_start": proc_self._block_start_next, 
                    "block_end": proc_self._block_end_next,
                    "inline_block_start": proc_self._inline_block_start_next, 
                    "inline_block_end": proc_self._inline_block_end_next,
                    "inline_block_level": None,
                    "compiled_address": Symbol(),
                    "compiled_instructions": None,
                })
                
                proc_self._block_start_next = False
                proc_self._block_end_next = False
                proc_self._inline_block_start_next = False
                proc_self._inline_block_end_next = False

                return instruction_resource
                
            setattr(self.__class__, instruction_name, append_instruction)
            
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
            # Create a new block if necessary
            if instruction["block_start"]:
                block_prev = block_current
                block_current = len(blocks)
                blocks.append([])
                inline_block_level.append(0)
            
            # Start the inline block, making sure to do this after starting the full block
            if instruction["inline_block_start"]:
                inline_block_level[block_current] += 1
                
            # Compile the instruction
            compilation_func = self._instruction_set[instruction["instruction"]]
            instruction["inline_block_level"] = inline_block_level[block_current]
            compiled_instructions = compilation_func(self, instruction)
            
            # Run some sanity checks on the output
            if not isinstance(compiled_instructions, list):
                raise TypeError(f"Expected list of compiled outputs from calling"
                                f" compilation function; received {compiled_instructions}")
                
            if len(compiled_instructions) == 0:
                raise ValueError(f"Instruction resulted in empty compilation:"
                                 f" {instruction}")
                
            if instruction["compiled_instructions"] is not None and not overwrite:
                raise ValueError("Instruction compilation is non-empty;"
                                 " set overwrite=True to overwrite.")
            
            # Add the compilation outputs to the block
            instruction["compiled_instructions"] = compiled_instructions
            blocks[block_current].append(instruction)
            
            # End the inline block, making sure to do this before ending the full block
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
                                    
    @classmethod
    @abstractmethod
    def assemble(cls, flattened_program):
        """
        Assembles a complete program into machine code appropriate for the 
        hardware executing the program.
        """
        pass
    
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
    
        
class PythonProcessor(Processor, ProcessorSubroutineMixin):
    """
    A processor capable of executing Python commands. For this 
    :class:`Processor`, compiling consists of generating strings containing
    Python code and assembly consists of calling the Python compiler on it.
    """
    
    # A dictionary indicating which types of arguments may be cached for 
    # retrieval at runtime. The keys are the types, and the 
    # values are strings indicating any post-processing needed at runtime to
    # extract the relevant argument data (such as extracting the value of a 
    # Symbol). This string is formatted with the key "obj" whose value is 
    # assigned as the object at runtime.
    cacheable_types = {Symbol       : "{obj}.value",
                       range        : "{obj}",
                       list         : "{obj}",
                       FunctionType : "{obj}",
                      }
    
    def __init__(self, instruction_limit=None):
        super().__init__(instruction_limit)
        
        # Create a ManagedResource for keeping track of imports and allowing
        # their members to be called
        def import_init(import_self, lib_name):
            import_self._lib_name = lib_name
            self(Operation("import", lib_name))
            
        def import_getattr(import_self, attr):
            return Operation("getattr", import_self._lib_name, attr)
                
        self.Import = ManagedResource("Import", 
                                      (), 
                                      {"__init__": import_init, 
                                       "__getattr__": import_getattr})
                
        # Keep track of loops so that we can give the iteration variables
        # unique names, otherwise nested loops will get messed up
        # Technically we could use the block level for this but we don't have
        # this at the macro level, so we'll just keep a running count since
        # any arbitrary unique value is fine
        self._loop_count = 0
    
    # Fundamentally, PythonProcessors only have one native instruction:
    # the ability to execute a line of Python code
    
    @Processor.instruction() 
    def __call__(self, instruction_resource):
        """
        Compile the execution of a Python statement. There are two ways to call
        a Python statement to be executed on a :class:`PythonProcessor`. 
        Assuming that the object `pyproc` is an instance of 
        :class:`PythonProcessor`:
        
        * `proc(op: str, **kwargs)`: Execute a line of Python encoded as a 
        string. 
        
        * `proc(op: Operation, **kwargs)`: Execute an :class:`Operation`,
        translating it into Python during compilation. 
        
        In both situations, before the compiled string(s) is/are returned, 
        their `format` methods are called with the elements of `kwargs` as 
        arguments.
        
        :param instruction_resource: instruction to compile
        :type instruction_resource: :class:`Instruction`
        """
        
        if len(instruction_resource["args"]) == 0:
            raise ValueError("At least one positional argument must be supplied"
                             " in order to specify the operation being performed.")
            
        op = instruction_resource["args"][0]
        compiled_kwargs = {k: self.compile_arg(v) for k,v in instruction_resource["kwargs"].items()}
        
        if isinstance(op, str):
            line_list = [op]
        elif isinstance(op, Operation):
            compiled_op = self.compile_arg(op)
            line_list = compiled_op if isinstance(compiled_op, list) else [compiled_op]
        else:
            raise TypeError(f"Operation of incompatible type ({type(op)}): {op}")
        
        indent = "    "*instruction_resource["inline_block_level"]
        if len(compiled_kwargs) > 0:
            return [indent + line.format(**compiled_kwargs) for line in line_list]
        return [indent + line for line in line_list]
    
    def call_subroutine(self, instruction_resource):
        """
        Implement subroutine calls by extracting the function from the
        :class:`PythonProcessor` instance at runtime, along with the arguments.
        """
        instruction_instance = f"self._Instruction.instances[{instruction_resource._resource_id}]"
        code_string = (f"self._subroutines[{instruction_resource['instruction']}]"
                       f"(*({instruction_instance}[\'args\']), "
                       f"**({instruction_instance}[\'kwargs\']))")
        return [code_string]
    
    # Some helper functions for use during compilation
        
    def compile_cached_object(self, obj):
        """
        Stores an object in this instance's data cache and returns a compiled statement that will retrieve it at runtime. The provided argument must have an entry in this class' `cacheable_types` dictionary.
        """
        if type(obj) not in self.cacheable_types:
            raise TypeError(f"Unable to cache object of type {type(obj)}: {obj}")
            
        cache_key = f"_cached_object{len(self._data)}"
        self._data[cache_key] = obj
        object_retrieval_string = f"self._data['{cache_key}']"
        return self.cacheable_types[type(obj)].format(obj=object_retrieval_string)
        
    def compile_arg(self, obj):
        """
        Translates an instruction argument (provided as an arbitrary object) 
        into an equivalent line of Python that creates it. Numeric and string 
        literals are compiled as strings that instantiate them, 
        :class:`Operation` instances are compiled into strings that execute 
        them with their corresponding operators, and :class:`Symbol` objects 
        are cached into this object's `data` cache.
        
        :param obj: Object to be converted
        :type obj: `str`, `Number`, :class:`Operation`, or :class:`Symbol`
        :return: A string representing a valid line of Python.
        :rtype: `str`
        """
        if isinstance(obj, Number) or isinstance(obj, bool):
            # A constant or literal, just return it since it should be able
            # to be directly converted into a string
            return str(obj)
        
        if isinstance(obj, str):
            # A literal string, we just need to add quotes for it to be valid
            return f"'{obj}'"
        
        if isinstance(obj, Operation):
            # Translate the operation being performed into a Python string that
            # can be compiled
            return self.compile_operation(obj)
            
        # Cache the object in the Processor's data dict for retrieval at 
        # runtime (the caching method will automatically check the type)
        return self.compile_cached_object(obj)
    
    def compile_operation(self, operation):
        """
        Translates an :class:`Operation` into an equivalent line of Python that
        computes it.
        
        :param operation: :class:`Operation` to be converted
        :type operation: :class:`Operation`
        :return: A string representing a valid line of Python.
        :rtype: str
        """
        if operation._op == "import":
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError("An import Operation must have exactly one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
                
            lib_name = operation._args[0]
            if not isinstance(lib_name, str):
                raise TypeError(f"Library name for import instruction must be of type str; received {lib_name}.")
            
            return f"import {lib_name}"
        
        if operation._op == "call":
            if len(operation._args) == 0:
                raise ValueError("A call Operation must have at least one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
                
            if isinstance(operation._args[0], str):
                callname = operation._args[0]
            elif isinstance(operation._args[0], FunctionType):
                callname = self.compile_cached_object(operation._args[0])
            else:
                callname = self.compile_arg(operation._args[0])
                
            compiled_args_kwargs = [self.compile_arg(arg) for arg in operation._args[1:]]
            compiled_args_kwargs += [f"{k}={self.compile_arg(v)}" for k,v in operation._kwargs.items()]
            
            tmp = f"{callname}({', '.join(compiled_args_kwargs)})"
            
            return tmp
        
        if operation._op == "getattr":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"A getattr Operation must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            if not isinstance(operation._args[1], str):
                raise TypeError(f"Attribute must be a string; received {operation._args[1]}")
                
            item = operation._args[0] if isinstance(operation._args[0], str) else self.compile_arg(operation._args[0], str)
            return f"{item}.{operation._args[1]}"
        
        if operation._op == "setattr":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"A setattr Operation must have exactly three positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            translated_value = self.compile_arg(operation._args[2])
            return f"setattr({operation._args[0]}, \"{operation._args[1]}\", {translated_value})"
        
        if operation._op == "getitem":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"A getitem Operation must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            translated_key = self.compile_arg(operation._args[1])
            return f"{operation._args[0]}[{translated_key}]"
        
        if operation._op == "setitem":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"A setitem Operation must have exactly three positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            translated_key = self.compile_arg(operation._args[1])
            translated_value = self.compile_arg(operation._args[2])
            return f"{operation._args[0]}[{translated_key}] = {translated_value}"
        
        if operation._op in ["neg", "abs", "invert"]:
            # Unary operators
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError(f"A {operation._op} Operation must have exactly one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_arg = self.compile_arg(operation._args[0])
            return f"operator.__{operation._op}__({compiled_arg})"
        
        if operation._op in ["eq", "ne", "lt", "gt", "le", 
                             "ge", "add", "sub", "mul", 
                             "floordiv", "truediv", "mod", 
                             "pow", "lshift", "rshift", "and",
                             "or", "xor"]:
            # Binary operators
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"A {operation._op} Operation must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_args = [self.compile_arg(arg) for arg in operation._args]    
            return f"operator.__{operation._op}__({compiled_args[0]}, {compiled_args[1]})"
        
        if operation._op in ["radd", "rsub", "rmul", 
                             "rfloordiv", "rtruediv", "rmod", 
                             "rpow", "rlshift", "rrshift", 
                             "rand", "ror", "rxor"]:
            # Right-handed binary operators
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with {operation._op} must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_args = [self.compile_arg(arg) for arg in operation._args]
            return f"operator.__{operation._op}__({compiled_args[1]}, {compiled_args[0]})"
        
        if operation._op in ["iadd", "isub", "imul", 
                             "ifloordiv", "itruediv", "imod", 
                             "ipow", "ilshift", "irshift", 
                             "iand", "ior", "ixor"]:
            # Right-handed binary operators
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with {operation._op} must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_args = [self.compile_arg(arg) for arg in operation._args]
            return f"operator.__{operation._op}__({compiled_args[0]}, {compiled_args[1]})"

        raise ValueError(f"Unable to translate operation {operation._op} with"
                         f" args={operation._args}, kwargs={operation._kwargs}.")
        
    # Add some macros for accessing the processor data

    def __getitem__(self, key):
        """
        Access a Python object in the namespace of the compiled program.
        """
        return Operation("getitem", f"self._data", key)
        
    def __setitem__(self, key, value):
        """
        Assign a value to a Python variable in the namespace of the compiled 
        program.
        
        :param key: Name of the variable to be assigned.
        :type key: `str`
        :param value: The value to assign to the variable
        """
        return self(Operation("setitem", f"self._data", key, value))
    
    def __getattr__(self, key):
        """
        Access a Python object in the namespace of the compiled program.
        """
        if key.startswith("_") or key == "Import" or key in self._instruction_set or hasattr(self.__class__, key):
            return super().__getattribute__(key)
        return Operation("getitem", f"self._data", key)
        
    def __setattr__(self, key, value):
        """
        Assign a value to a Python variable in the namespace of the compiled 
        program.
        
        :param key: Name of the variable to be assigned.
        :type key: `str`
        :param value: The value to assign to the variable
        """
        if key.startswith("_") or key == "Import" or key in self._instruction_set or hasattr(self.__class__, key):
            return super().__setattr__(key, value)
        self(Operation("setitem", f"self._data", key, value))
    
    # Macros for control flow
    
    @contextmanager
    def test(self, condition):
        """
        A context manager for testing a condition with a Python `if` statement.
        A block with the statement body is automatically created and exited 
        when entering and exiting the context, respectively.
        
        :param condition: Condition to test. May be of any type able to be
        compiled as an argument
        """
        self("if {condition}:", condition=condition)
        self.block_start(inline=True)
        yield
        self.block_end(inline=True)
        
    @contextmanager
    def loop(self, iterable, use_symbols=False):
        """
        A context manager for iterating over an iterable with a Python `for`
        statement. A block with the loop body is automatically created and
        exited when entering and exiting the context, respectively. 
        :class:`Operation` objects retrieving the iteration index and the 
        elements are yielded in a tuple, similar to the behavior of 
        `enumerate`. Optionally, these may be encapsulated in (and yielded as)
        :class:`Symbol` objects which are assigned at the start of the loop 
        body, which may be useful in certain applications.
        """
        # Create Operation objects that will retrieve the loop variables
        idx_operation = self[f'loop{self._loop_count}_idx']
        element_operation = self[f'loop{self._loop_count}_element']
        
        if use_symbols:
            idx_symbol = Symbol()
            element_symbol = Symbol()
        
        # Create the loop statement itself
        self(f"for {{idx}},{{element}} in enumerate({{iterable}}):", 
                 idx=idx_operation, element=element_operation, iterable=iterable)
        
        # Start the block
        self.block_start(inline=True)
        
        # Assign symbols, if they were created
        if use_symbols:
            self("{symbol}.assign({idx}, force=True)", 
                     symbol=idx_symbol, idx=idx_operation) 
            self("{symbol}.assign({element}, force=True)", 
                     symbol=element_symbol, element=element_operation) 

        self._loop_count += 1
        
        # Yield either the data reference to the iteration variables or the
        # Symbols encapsulating them
        yield (idx_symbol if use_symbols else idx_operation,
               element_symbol if use_symbols else element_operation)
        
        self.block_end(inline=True)
        
    @contextmanager
    def wait_until(self, condition):
        """
        A context manager for waiting for a condition with a Python `while` 
        statement. Note that the loop will continue to execute as long as the
        provided condition is NOT satisfied. A block with the statement body
        is automatically created and exited when entering and exiting the 
        context, respectively.
        
        :param condition: Condition to test. May be of any type able to be
        compiled as an argument
        """
        self("while not {condition}:", condition=condition)
        self.block_start(inline=True)
        yield
        self.block_end(inline=True)
        
    def assemble(self):
        self._assembled_program = compile("\n".join(self._compiled_program), "", "exec")
    
    def run(self):
        """
        This function executes the internally-stored program. This is expected 
        to be called on the hardware running the Python environment that the 
        program targets.
        """
        exec(self._assembled_program)
        
            
    