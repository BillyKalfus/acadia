import pickle
from numbers import Number
from abc import ABC, abstractmethod

from ..assembler import Operation, Processor, Symbol, ManagedResource

class Processor(ABC):
    _instruction_set = {}
    
    @classmethod
    def instruction(cls, name=None):
        """
        A decorator for specifying an instruction "natively" implemented by the entity abstracted by this :class:`Processor`. The decorated method is understood to translate an :class:`Instruction` object (passed as the sole argument) into machine code for the object that will be programmed with these instructions, the exact format of which is left up to the specific subclasses.   
        
        Calling a decorated method on a :class:`Processor` instance expresses an intent to command the :class:`Processor` to execute the represented instruction at that point in the program, meaning that the underlying translation function should not be called yet. To implement this behavior, the default instance initializer will iterate through the class instruction set and bind a new method with the name of the decorated function to the instance which, when called, will add an :class:`Instruction` to the program list. Then, when an instance is translating its program list, it can refer to the translation functions stored in the class instruction set.
        """
        def named_instruction_decorator(translation_func):
            # We will intentionally return None from this decorator since we don't want to actually create a
            # function for the class, we just want to cache it in the instruction set
            cls._instruction_set[translation_func.__name__ if name is None else name] = translation_func
            
        return named_instruction_decorator
    
    def __init__(self, instruction_limit=None, preassemble=False):
        """
        A base class for objects that represent entities capable of being commanded by a set of native "instructions". Native instructions are defined in subclasses by decorating methods that produce machine code with :meth:`Processor.instruction` (see its documentation for a description of how instructions are implemented). 
        
        Instances of :class:`Processor` maintain an internal list of all instructions invoked on it, referred to as the "program list". The order of the instructions inside the program list is understood to be the order in which the instructions will execute, in the absence of branching. 
        
        In some situations it is desirable to define a distinct "block" of instructions which are to be executed (potentially conditionally), and then have program flow continue from the point immediately following that at which the block was invoked. The compiler must decide where to place the instructions comprising the block, with the option of either inserting them at the point at which the block is declared, or placing them in a disjoint region of program memory to which execution is branched when the block is invoked, and returned from when the block is completed.
        
        A choice between these two methods will depend on whether the block is expected to be executed a majority of the time (or unconditionally); if it is, it is more desirable to place the instructions at the point of invocation to avoid the additional latency associated with branching, at the expense of increased program memory usage should the block need to be reused in multiple places. This concept arises in other programming languages when defining subroutines, typically referred to as "inlining" the subroutine. In contrast, if it is expected that the block will typically not be executed (for example, because a condition determining its execution will typically not be satisfied), it is preferable to place the block elsewhere so that the majority of the time, execution will simply continue past the conditional branch instruction with no additional latency incurred.
        
        The ability to dynamically choose between these methods is referred to as "speculative execution" and is a hardware feature of most modern processors (which, rather than deciding where to place instructions, makes a decision about the location in instruction memory from which to load the instruction following the branch). Here, we explicitly expose this decision to the user with the keyword `inline`, 
        
        Compiling a program for a :class:`Processor` consists of three distinct steps:
        
        #. Resource Allocation
            
            This first step occurs implicitly when the Python code containing the program is executed. When instruction functions are called on :class:`Processor` objects in a script, this creates :class:`Instruction` objects which are then stored in the program list. These objects contain metadata about that particular instruction invocation, such as the arguments to the instruction and any resources requested from the :class:`Processor` needed to carry out the instruction. Because classes of metaclass :class:`ManagedResource` assign addresses to their instances upon creation, when the script finishes all addressable resources for all processors will have been assigned and allocated. At the end of this stage, the program list will be fully populated and all :class:`Symbol` objects representing automatically-allocated memory locations will be assigned.
            
        #. Compilation
        
            In this step, each instruction created during symbolic compilation is translated into one or more native instructions. Because the functions that the user calls when commanding a :class:`Processor` are directly representative of its native instructions, the primary function of this step is to translate the symbolic arguments passed to the instructions and potentially insert additional instructions when needed (such as for expanding compound expressions). At the end of this stage, the "compiled" field of all instructions will be populated with data representing the compiled instruction and arguments. While this data is ultimately hardware-specific, it is assumed that the data is in a form that allows it to be directly translated into machine code with no further symbolic solving (except for potentially retrieving the value of an assigned :class:`Symbol`). The program list will also be rearranged to match the desired block structure.
        
        #. Assembly
        
            Finally, the data stored as a result of compilation is converted into machine code for the hardware. All :class:`Symbol` objects contained in instructions will be accessed, and simplifications may be performed. 
        
        :param instruction_limit: Maximum number of instructions allowed to be called on the :class:`Processor`.
        :type instruction_limit: int, optional
        :param pretranslate: If `True`, instructions are translated at the time of invocation.
        :type pretranslate: bool, optional
        """
        
        # The custom resource for storing instructions
        self.Instruction = ManagedResource(f"{self.__class__}Instruction", (dict,), {}, instance_limit=instruction_limit)
        
        # For every instruction, bind a new method to the instance with the name of the instruction
        for instruction_name,translator in self.__class__._instruction_set.items():
            def append_instruction(proc_self, *args, **kwargs):
                """
                Append an instruction to a program list. The `dict` encapsulated by the :class:`ManagedResource` contains a few dedicated fields:
                
                * `instruction`: The name of the instruction to execute, which is used to look up the translation function in the dictionary defining the class' instruction set.
                * `args`: Positional arguments provided to the instruction when called.
                * `kwargs`: Keywords arguments provided to the instruction when called.
                * `block_start`: If `True`, indicates that this instruction is the first in a non-inlined block
                * `block_end`: If `True`, indicates that this instruction is the lats in a non-inlined block
                * `cache`: A list of objects cached during assembly
                """
                instruction_resource = proc_self.Instruction({"instruction": instruction_name, "args": args, "kwargs": kwargs, "cache": [], block_start=proc_self.block_start, block_end=proc_self.block_end})
                proc_self.block_start = False
                proc_self.block_end = False
                if preassemble:
                    proc_self.translate_instruction(instruction_resource)
                return instruction_resource
                
            setattr(self, instruction_name, MethodType(append_instruction, self))
            
    def block_start(self):
        """
        Indicate that the next instruction called is the first in a non-inlined block.
        """
        self.block_start = True
        
    def block_end(self):
        """
        Indicate that the next instruction called is the last in a non-inlined block.
        """
        self.block_end = True
    
    @classmethod
    @abstractmethod
    def compile_single(cls, instruction_resource):
        """
        Compiles a single instruction in a program.
        """
        pass
        
    def compile(self):
        """
        Compiles the complete program by iterating through the program list and calling :meth:`comple_single` on every instruction, while restructuring the program to obey the desired block structure.
        """
        blocks = [[]]
        block_prev = None
        block_current = 0
        for instruction in self.Instruction.instances:
            if instruction["block_start"]:
                blocks.append([])
                block_prev = block_current
                block_current = len(blocks)
                
            compiled_instruction = self.compile_single(instruction)
            blocks[block_current].append(compiled_instruction)
            
            if instruction["block_end"]:
                block_current = block_prev
                
        return blocks
        
class PythonProcessor(Processor):
    _subroutines = []
    
    def __init__(self, instruction_limit=None, pretranslate=False):
        """
        A processor capable of executing Python commands. For this :class:`Processor`, compiling consists of generating strings containing Python code and assembly consists of calling the Python compiler on it.
        """
        super().__init__(instruction_limit, pretranslate)
        
        # Create an object that will accept arbitrary attributes, which we'll use as a stand-in for global variables during runtime
        # https://stackoverflow.com/questions/2280334/shortest-way-of-creating-an-object-with-arbitrary-attributes-in-python
        self.data = {}
        
        # Create a ManagedResource for keeping track of imports and allowing their members to be called
        def import_init(import_self, lib_name):
            import_self._lib_name = lib_name
            self(Operation("import", lib_name))
            
        def import_getattr(import_self, attr):
            return Operation("__getattr__", lib_name, attr)
                
        self.Import = ManagedResource("Import", (,), {"__init__": import_init, "__getattr__": import_getattr})
        operator = self.Import("operator")
        
    @classmethod
    def subroutine(cls, func):
        """
        A decorator for creating callable subroutines from Python functions. Because `__getattr__` cannot distinguish between method calls and member field accesses, the primary purpose of this decorator is to indicate that when the decorated function is accessed as an attribute of a :class:`Processor` instance, an :class:`Instruction` should be generated that calls the corresponding subroutine (which is stored in the instance). Because of this, when a subroutine is called in the arguments to a function, the :class:`Instruction` created by the subroutine call will be used to populate a new temporary variable, which is then provided to the function.   
        """
        subroutine_idx = len(cls._subroutines)
        cls._subroutines.append(func)
        
        @cls.instruction(name=func.__name__)
        def subroutine_instruction(self, instruction_resource):
            # Because this is meant to be called at runtime, we can't just use the arguments provided,
            # we have to build a string that will extract them at runtime from the processor's program
            instruction_instance = f"self.Instruction.instances[{instruction_resource._resource_id}]"
            code_string = f"PythonProcessor._subroutines[{subroutine_idx}](*({instruction_instance}[\'args\']), **({instruction_instance}[\'kwargs\']))"
            instruction_resource["compiled"] = code_string
        
        return subroutine_instruction
    
    @Processor.instruction() 
    def __call__(self, instruction_resource):
        """
        Calling a :class:`PythonProcessor` object executes a statement. There are multiple ways to specify the execution; if `processor` is an instance of :class:`Processor`, then the following call signatures apply: 
        1) `processor(statement)`: If `statement` is a `str`, then it is compiled. If `statement` is an :class:`Operation`, it is converted into a string and compiled. The compiled code is then stored in the result :class:`Instruction`.
        """
        
        if len(args) == 0:
            raise ValueError("At least one positional argument must be supplied in order to specify the operation being performed.")
            
        op = args[0]

        if isinstance(op, str):
            instruction_resource["code"] = op
            return compile(op, "", "eval")
        elif isinstance(op, Operation):
            code = self.cls.compile_arg(op, instruction_resource)
            instruction_resource["code"] = code
            return compile(code, "", "eval")

        raise TypeError(f"Operation of incompatible type ({type(op)}): {op}")

    def __getattr__(self, attr):
        """
        Access a Python object in the namespace of the compiled program. While it's desirable to be able to call arbitrary functions by calling `processor.<function name>`, this is difficult to implement because we can't know whether the attribute being accessed is a function being called or a variable being accessed, and only the former requires an instruction to be generated. It is this reason that in order to call a function in the global scope, one must either define a subroutine or call this instance's `__call__` method.
        """
        return Operation("__getitem__", f"self.data", attr)
        
    def __setattr__(self, attr, value):
        """
        Assign a value to a Python variable in the namespace of the compiled program.
        :param attr: Name of the variable to be assigned.
        :type attr: str
        :param value: The value to assign to the variable
        """
        return Operation("__setitem__", f"self.data", attr, value)
    
    @classmethod
    def compile_arg(cls, obj, instruction_resource):
        """
        Translates an instruction argument (provided as an arbitrary object) into an equivalent line of Python that creates it. If it can't be created at runtime, it is cached in the instruction resource and code is added to retrieve it at runtime.
        :param obj: Object to be converted
        :return: A string representing a valid line of Python.
        :rtype: str
        """
        if isinstance(obj, Number) or isinstance(obj, bool):
            # A constant or literal, just return it since it should be able to be directly converted into a string
            return str(obj)
        
        if isinstance(obj, str):
            # A literal string, we just need to add quotes for it to be valid
            return f"'{obj}'"
        
        if isinstance(obj, Operation):
            # Translate the operation being performed into a Python string that can be compiled
            return cls.compile_operation(obj, instruction_resource)
            
        # Other type (potentially an object we want to reference at runtime)
        # Cache it and return the string that retrieves it
        # add some special behavior at runtime
        cache_idx = len(instruction_resource["cache"])
        instruction_resource["cache"].append(obj)
        return f"self.Instruction.instances[{instruction_resource._resource_id}][\"cache\"][{cache_idx}]{'.value' if isinstance(obj, Symbol) else ''}"
    
    @classmethod
    def compile_operation(cls, operation, instruction_resource):
        """
        Translates a symbolic operation into an equivalent line of Python.
        :param operation: :class:`Operation` to be converted
        :type operation: :class:`Operation`
        :return: A string representing a valid line of Python.
        :rtype: str
        """
        if operation._op == "__getattr__":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with __getattr__ must have exactly two positional arguments.")
            return f"getattr({operation._args[0]}, \"{operation._args[1]}\")"
        if operation._op == "__setattr__":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with __setattr__ must have exactly three positional arguments.")
            translated_value = cls.compile_arg(operation._args[2], instruction_resource)
            return f"setattr({operation._args[0]}, \"{operation._args[1]}\", {translated_value})"
        if operation._op == "__getitem__":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with __getitem__ must have exactly two positional arguments.")
            translated_key = cls.compile_arg(operation._args[1], instruction_resource)
            return f"{operation._args[0]}[{translated_key}]"
        if operation._op == "__setitem__":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with __setitem__ must have exactly three positional arguments.")
            translated_key = cls.compile_arg(operation._args[1], instruction_resource)
            translated_value = cls.compile_arg(operation._args[2], instruction_resource)
            return f"{operation._args[0]}[{translated_key}] = {translated_value}"
        if operation._op == "__call__":
            if len(operation._args) == 0 or len(operation._kwargs) != 0:
                raise ValueError("An Operation with __call__ must have at least one positional argument.")
            callname = operation._args[0]
            translated_args = [cls.compile_arg(arg, instruction_resource) for arg in operation._args[1:]]
            translated_kwargs = [f"{k}={cls.compile_arg(v, instruction_resource)}" for k,v in operation._kwargs.items()]
            return f"{callname}({','.join(translated_args)}, {','.join(translated_kwargs)})"
        if operation._op in ["__neg__", "__abs__", "__invert__"]:
            # Unary operators
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with {operation._op} must have exactly one positional argument.")
            return f"operator.{operation._op}({operation._args[0]})"
        if operation._op in ["__eq__", "__ne__", "__lt__", "__gt__", "__le__", "__ge__", "__add__", "__sub__", "__mul__", "__floordiv__", "__truediv__", "__mod__", "__pow__", "__lshift__", "__rshift__", "__and__", "__or__", "__xor__"]:
            # Binary operators
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with {operation._op} must have exactly two positional arguments.")
            return f"operator.{operation._op}({operation._args[0]}, {operation._args[1]})"
        if operation._op in ["__radd__", "__rsub__", "__rmul__", "__rfloordiv__", "__rtruediv__", "__rmod__", "__rpow__", "__rlshift__", "__rrshift__", "__rand__", "__ror__", "__rxor__"]:
            # Right-handed binary operators
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"An Operation with {operation._op} must have exactly two positional arguments.")
            return f"operator.{operation._op}({operation._args[1]}, {operation._args[0]})"

        raise ValueError(f"Unable to translate operation {operation._op}")
    
    def run(self):
        """
        This function executes the internally-stored program. This is expected to be called on the hardware running the Python environment that the program targets.
        """
        for op in self.Instruction.instances:
            
                raise TypeError(f"Invalid type for specifying operation in instruction {op}")
    