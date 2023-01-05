from ..assembler import Operation, Processor, Symbol, ManagedResource

class Processor(ABC):
    instruction_set = {}
    
    @classmethod
    def instruction(cls, func):
        """
        A decorator for specifying an instruction belonging to the instruction set of the :class:`Processor`. The provided method is understood to "translate" the associated instruction call and return machine code for the object that will be programmed with these instructions, the exact format of which is left up to the specific derived classes. 
        Calling an instruction method on the :class:`Processor` class itself is understood to express an intent to translate an instruction with provided arguments by calling the underlying function. However, calling the method on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction at that point in the program, meaning that the underlying function should not be called but should simply be added as an entry in the instance's instruction list. This decorator implements this behavior by returning a `classmethod` which will then be automatically bound to the class. Then, the default initializer of this class will iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method, will make a request from the object's . 
        """
        cls.instruction_set.append(func)
        return staticmethod(func)
    
    """
    A base class for objects that represent entities capable of being commanded by a set of native "instructions". Native instructions are defined in derived classes by decorating methods that produce their machine code with :meth:`Processor.instruction`.
    Because calling a method decorated with :meth:`instruction` on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction, an entry in the instance's instruction list should be added. This is handled by having trhe initializer iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method will make a request from the object's :field:`_instructions` ManagedResource. 
    :param instruction_limit: Maximum number of instructions allowed to be called on the :class:`Processor`.
    :type instruction_limit: int
    """
    def __init__(self, instruction_limit=None):
        self.Instruction = ManagedResource("Instruction", (dict,), {}, instance_limit=instruction_limit)
        
        # For every instruction, bind a new method to the instance with the name of the instruction
        for instruction in instruction_set:
            def append_instruction(self, *args, **kwargs):
                instruction_resource = self.Instruction({"instruction": instruction, "args": args, **kwargs})
                return instruction_resource.return_value
                
            setattr(self, instruction.__name__, MethodType(append_instruction, self))
                        
    def __new__(cls, *args, **kwargs):
        """
        Prevents a :class:`Processor` from being directly instantiated. This is typically handled with the `abc` module, but because :class:`Processor` doesn't actually implement any abstract methods, ABCMeta will not prevent :class:`Processor` from being directly instantiated. Therefore, to implement this, we'll just override :meth:`__new__` and fail to return a new object if its class is :class:`Processor`.
        """
        if cls is Processor:
            raise TypeError("Processor cannot be directly instantiated; one must define a subclass.")
        
        return super().__new__(cls, *args, **kwargs)
    
    @abstractmethod
    def translate(self):
        """
        A method for translating the symbolic instructions contained in the instance into a representation that is meaningful for the particular hardware abstracted by this :class:`Processor`. There is no restriction on the return type of this object, but it is understood that the returned value must be capable of being "executable", whatever that may mean for a given physical processor.
        """
        pass

class PythonProcessor(Processor):
    
    """
    A processor capable of executing Python commands.
    """
    def __init__(self):
        # Create a ManagedResource for keeping track of imports and allowing their members to be called
        def import_init(import_self, lib_name):
            import_self._lib_name = lib_name
            
        def import_getattr(import_self, attr):
            return Operation("getattr", import_self, attr)
        
        self.Import = ManagedResource("Import", (), {"__init__": import_init, "__getattr__": import_getattr})
        
    def subroutine(self, func):
        """
        A decorator for creating callable subroutines from Python functions. Because `__getattr__` cannot distinguish between method calls and member field accesses, the primary purpose of this decorator is to indicate that the decorated function, when accessed as an attribute of its :class:`Processor`, should produce an :class:`Instruction` for calling the corresponding subroutine. Because of this, when a subroutine is called in the arguments to a function, the :class:`Instruction` created during the subroutine called will be used to populate a new temporary variable, which is then provided to the function.   
        """
        # TODO: implement this
        
    @Processor.instruction
    def exec(code_string):
        """
        :return: A code object compiled from the given string. 
        """
        return compile(code_string, "", "exec")
    
    def __getattr__(self, attr):
        """
        Access a Python object in the namespace of the compiled program. This cannot be considered a native instruction because we can't know whether the attribute being accessed is a function being called or a variable being accessed, and only the former requires an instruction to be generated. It is this reason that the only meaningful way to call a function in the global scope is to define a subroutine.
        A :class:`Symbol` is returned so that it may be operated on. 
        """
        return Symbol(attr)
        
    @Processor.instruction
    def __setattr__(self, name, value):
        """
        Assign a value to a Python variable in the namespace of the compiled program.
        :param name: Name of the variable
        :type name: str
        :param value: The value to assign to the variable
        :
        """
        # TODO: implement translation for this
        # TODO: if the value is an Instruction, this indicates that we're trying to set a variable to the return value of something. Update the Instruction dict accordingly
    