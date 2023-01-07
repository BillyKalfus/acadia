import pickle
import uuid
from numbers import Number
from ..assembler import Operation, Processor, Symbol, ManagedResource

class Processor:
    _instruction_set = {}
    
    @classmethod
    def instruction(cls, name=None):
        """
        A decorator for specifying an instruction "natively" implemented by the entity abstracted by this :class:`Processor`. The provided method is understood to "translate" an :class:`Instruction` object passed as the sole argument into machine code for the object that will be programmed with these instructions, the exact format of which is left up to the specific derived classes. The :class:`Instruction` object is a subclass of `dict` and a :class:`ManagedResource`.
        Calling a decorated method on the :class:`Processor` class itself is understood to express an intent to translate an instruction with provided arguments by calling the underlying translation function. However, calling the method on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction at that point in the program, meaning that the underlying translation function should not be called but should simply be added as an entry in the instance's instruction list. This decorator implements this behavior by returning a `classmethod` which will then be automatically bound to the class. Then, the default initializer of this class will iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method, will add an :class:`Instruction` to the program. 
        """
        def named_instruction_decorator(translation_func):
            cls._instruction_set[translation_func.__name__ if name is None else name] = translation_func
            return staticmethod(func)
        
        return named_instruction_decorator
    
    """
    A base class for objects that represent entities capable of being commanded by a set of native "instructions". Native instructions are defined in derived classes by decorating methods that produce their machine code with :meth:`Processor.instruction`.
    Because calling a method decorated with :meth:`instruction` on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction, an entry in the instance's instruction list should be added. This is handled by having trhe initializer iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method will make a request from the object's :field:`_instructions` ManagedResource. 
    
    Optionally, one can choose to pretranslate the program, in which case instructions will be translated to their binary equivalents when invoked.
    :param instruction_limit: Maximum number of instructions allowed to be called on the :class:`Processor`.
    :type instruction_limit: int, optional
    :param pretranslate: If `True`, instructions are translated at the time of invocation.
    :type pretranslate: bool, optional
    """
    def __init__(self, identifier=None, instruction_limit=None, pretranslate=False):
        self.Instruction = ManagedResource("Instruction", (dict,), {}, instance_limit=instruction_limit)
        self._translated_program = []
        self._identifier = identifier if identifier is not None else f"processor{uuid.uuid4().int}"
        
        # For every instruction, bind a new method to the instance with the name of the instruction
        for instruction_name,translator in self.__class__._instruction_set.items():
            def append_instruction(proc_self, *args, **kwargs):
                instruction_resource = proc_self.Instruction({"instruction": instruction_name, "translator": translator, "args": args, **kwargs, "cache": []})
                if pretranslate:
                    translated_resource = translator(proc_self, instruction_resource)
                    proc_self._translated_program.append(translated_resource)
                return instruction_resource
                
            setattr(self, instruction_name, MethodType(append_instruction, self))
                        
    def __new__(cls, *args, **kwargs):
        """
        Prevents a :class:`Processor` from being directly instantiated. This is typically handled with the `abc` module, but because :class:`Processor` doesn't actually implement any abstract methods, ABCMeta will not prevent :class:`Processor` from being directly instantiated. Therefore, to implement this, we'll just override :meth:`__new__` and fail to return a new object if its class is :class:`Processor`.
        """
        if cls is Processor:
            raise TypeError("Processor cannot be directly instantiated; one must define a subclass.")
        
        return super().__new__(cls, *args, **kwargs)
    
    def translate(self, force=False):
        """
        A method for translating the symbolic instructions contained in the instance into a representation that is meaningful for the particular hardware abstracted by this :class:`Processor`. There is no restriction on the return type of this object, but it is understood that the returned value must be capable of being "executable", whatever that may mean for a given physical processor.
        """
        if len(self._translated_program) > 0:
            raise ValueError("Attempted translation of already-translated program. If this is intentional, set force=True.")
            
        self._translated_program = []
        
        for 

class PythonProcessor(Processor):
    _subroutines = []
    
    """
    A processor capable of executing Python commands. 
    """
    def __init__(self, identifier=None, instruction_limit=None, pretranslate=False):
        super().__init__(identifier, instruction_limit, pretranslate)
        
        # Create an object that will accept arbitrary attributes, which we'll use as a stand-in for global variables during runtime
        # https://stackoverflow.com/questions/2280334/shortest-way-of-creating-an-object-with-arbitrary-attributes-in-python
        self.data = type('', (), {{}})()
        
        # Create a ManagedResource for keeping track of imports and allowing their members to be called
        def import_init(import_self, lib_name):
            import_self._lib_name = lib_name
            self("import", lib_name)
            
        def import_getattr(import_self, attr):
            return Operation("__getattr__", lib_name, attr)
                
        self.Import = ManagedResource("Import", (,), {"__init__": import_init, "__getattr__": import_getattr})
        
    @classmethod
    def subroutine(cls, func):
        """
        A decorator for creating callable subroutines from Python functions. Because `__getattr__` cannot distinguish between method calls and member field accesses, the primary purpose of this decorator is to indicate that when the decorated function is accessed as an attribute of a :class:`Processor` instance, an :class:`Instruction` should be generated that calls the corresponding subroutine (which is stored in the instance). Because of this, when a subroutine is called in the arguments to a function, the :class:`Instruction` created by the subroutine call will be used to populate a new temporary variable, which is then provided to the function.   
        """
        cls._subroutines.append(func)
        
        @cls.instruction(name=func.__name__)
        def subroutine_instruction(self, instruction_resource):
            # Because this is meant to be called at runtime, we can't just use the arguments provided,
            # we have to build a string that will extract them at runtime from the processor's program
            instruction_instance = f"{self._identifier}.Instruction.instances[{instruction_resource._resource_id}]"
            code_string = f"{func.__name__}(*({instruction_instance}[\'args\']), **({instruction_instance}[\'kwargs\']))"
            instruction_resource["code"] = code_string
            return compile(code_string, "", "eval")
        
        return subroutine_instruction
    
    @Processor.instruction 
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
            code = translate_obj(op, self._identifier, instruction_resource)
            instruction_resource["code"] = code
            return compile(code, "", "eval")

        raise TypeError(f"Operation of incompatible type ({type(op)}): {op}")

    def __getattr__(self, attr):
        """
        Access a Python object in the namespace of the compiled program. While it's desirable to be able to call arbitrary functions by calling `processor.<function name>`, this is difficult to implement because we can't know whether the attribute being accessed is a function being called or a variable being accessed, and only the former requires an instruction to be generated. It is this reason that in order to call a function in the global scope, one must either define a subroutine or call this instance's `__call__` method.
        """
        return Operation("__getattr__", f"{self._identifier}.data", attr)
        
    def __setattr__(self, attr, value):
        """
        Assign a value to a Python variable in the namespace of the compiled program.
        :param attr: Name of the variable to be assigned.
        :type attr: str
        :param value: The value to assign to the variable
        """
        return Operation("__setattr__", f"{self._identifier}.data", attr, value)
    
    @staticmethod
    def translate_obj(obj, identifier, instruction_resource):
        """
        Translates a symbolic object into an equivalent line of Python. 
        :param obj: Object to be converted
        :type obj: any subclass of :class:`Operable`
        """
        if isinstance(obj, Number) or isinstance(obj, str) or isinstance(obj, bool):
            # A constant or literal, just return it since it should be able to be directly converted into a string
            return obj
        
        if isinstance(obj, Operation):
            # Translate the operation being performed into a Python string that can be compiled
            if obj._op == "__getattr__":
                if len(obj._args) != 2 or len(obj._kwargs) != 0:
                    raise ValueError(f"An Operation with __getattr__ must have exactly 2 positional arguments.")
                return f"{obj._args[0]}.{obj._args[1]}"
            if obj._op == "__setattr__":
                if len(obj._args) != 3 or len(obj._kwargs) != 0:
                    raise ValueError(f"An Operation with __setattr__ must have exactly 3 positional arguments.")
                translated_value = translate_obj(obj._args[2], identifier, instruction_resource)
                return f"{obj._args[0]}.{obj._args[1]} = {translated_value}"
            
        if isinstance(obj, Symbol):
            # Cache the Symbol and return a string that retrieves its value at runtime
            cache_idx = len(instruction_resource["cache"])
            instruction_resource["cache"].append(obj)
            return f"{identifier}.Instruction.instances[{instruction_resource._resource_id}][\"cache\"][{cache_idx}].value"
            
        # Other type (potentially an object we want to reference at runtime)
        # Cache it and return the string that retrieves it
        cache_idx = len(instruction_resource["cache"])
        instruction_resource["cache"].append(obj)
        return f"{identifier}.Instruction.instances[{instruction_resource._resource_id}][\"cache\"][{cache_idx}]"
                    
    
    def run(self):
        """
        This function executes the internally-stored program. This is expected to be called on the hardware running the Python environment that the program targets.
        """
        for op in self.Instruction.instances:
            
                raise TypeError(f"Invalid type for specifying operation in instruction {op}")
    