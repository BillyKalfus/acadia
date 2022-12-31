"""
assembler.py
Assembler for the microarchitecture of the Acadia quantum control system.
William Kalfus, Yale University
December 2022
"""
from types import MethodType

class Operable(type):
    OPERATORS = ["eq", "ne", "neg", "abs", "invert", "add", "radd", "sub", "rsub", "mul", "rmul", "floordiv", "rfloordiv", "truediv", "rtruediv", "mod", "rmod", "pow", "rpow", "lshift", "rlshift", "rshift", "rrshift", "and", "rand", "or", "ror", "xor", "rxor", "bool", "len", "contains", "iter", "getitem", "setitem", "enter", "exit", "copy", "deepcopy"]
    
    """
    A metaclass used to capture operators acting on instances of derived classes and return a symbolic representation of the operator call.
    """ 
    def __new__(cls, name, bases, dct):
        for op in OPERATORS:
            def op_func(*args, **kwargs):
                return Operation(op, *args, *kwargs)
            dct[f"__{op}__"] = op_func
                
        return super().__new__(cls, name, bases, dct)
    
class Operation(metaclass=Operable):
    """
    A class encapsulating operations to be performed instances of :class:`Operable` classes. :class:`Operation` objects can also respond to operators in the same manner that produces them (since :class:`Operable` is its metaclass), thereby creating nested :class:`Operation` objects. It is left to the eventual receiver of the :class:`Operation` object to decide whether this is acceptable.
    :param op: An object representing the operation being performed on the provided arguments. This can be any object, since it is up to the eventual receiver of these objects to interpret this field. For example, the eventual receiver may want this to be a callable object that it can directly call on the arguments, or it may want it to be a string that it can interpret, etc.
    :type op: object
    """
    def __init__(self, func_name, *args, **kwargs):          
        self._func = func
        self._args = args
        self._kwargs = kwargs
        
    def __str__(self):
        return f"Operation({*self._args}, {*self._kwargs})"
    
class Symbol(metaclass=Operable):
    """
    A symbolic variable with a value not necessarily known to the user but guaranteed to be available at the time of translation. A canonical example of an :class:`Operable` class, it allows objects or values to be distributed throughout a program that depend on the future decisions of higher-level entities (e.g., a program translator deciding memory locations or array lengths). This requires operator evaluation to be deferred to a future time (and potentially in different ways, depending on the involved objects). In such a situation, this object acts as a placeholder for the desired object.
    :param value: The value of the :class:`Symbol`, if known at instantiation. If not provided, may be assigned later.
    :type value: object, optional
    """
    def __init__(self, value=None):
        self._value = value
        self._assigned = value != None
                
    def assign(self, v, force=False):
        if Symbol.assigned(self) and not force:
            raise ValueError("Attempted reassignment of Symbol. If you're sure that this is the correct operation, set argument force=True.")
            
        self._assigned = True
        self._value = v
    
    @classmethod
    def assigned(obj):
        """
        Analyzes the provided object to determine whether all encapsulated :class:`Symbol` objects are assigned. It evaluates :class:`Operation` objects by recursively checking on their arguments, and it evaluates :class:`Symbol` objects by checking whether they are assigned, and if so, whether their value is solvable. All other objects are assumed to be solvable.
        :param obj: Object to check for solvability.
        :return: `True` if the provided object has all 
        """
        if isinstance(obj, Operation):
            return reduce(and, map(Symbol.assigned, obj._args + [v for k,v in obj._kwargs.items()]))
        elif isinstance(obj, Symbol):
            return obj._assigned and Symbol.assigned(obj._value)
        return True
        
class ManagedResource(Operable):
    """
    Metaclass for creating autonomous hardware resource factories. This metaclass implements resource allocation by assigning unique IDs to created instances of derived classes (henceforth referred to as "resource objects"), as well as resource recycling by tracking whether the resource object is released in the future. Its implementation as a metaclass allows resource tracking to take place in a class field, which in turn allows multiple identical resource factories to be created and have them each track their own resources without interference simply by subclassing :class:`ManagedResource`. This also allows the resource objects themselves to be of any type. Additionally, it allows allocation to occur immediately when resource objects are created and potentially return existing resource objects if necessary. This is a subclass of :class:`Operable`, so that actions on resource objects can be inferred by analyzing produced :class:`Operation` objects.
    :param instance_limit: The maximum number of instances that may be created by the class.
    :type instance_limit: int, optional
    :param use_instance_size: If `True`, indicates that the allocation offset should be increased by an amount equal to the provided `size` keyword.  
    :type use_instance_size: bool, optional
    """
    def __new__(cls, name, bases, dct, instance_limit=None, use_instance_size=True):
        
        def cls_new(cls, allocate=True, resource_id=None, *inst_args, **inst_kwargs):
            """
            Create a new instance representing a hardware resource. If a resource limit has been provided and reached, existing allocations will be checked to see if they were released, and if so, may be returned. Created resources can also defer allocation until the future, allowing strategic control of the allocation value.
            :param allocate: If `False`, the returned instance will not be added to the list of managed resources, the :field:`resource_id` field will not be assigned, and the class :field:`allocation_index` field will not be updated.
            :type allocate: bool
            :param resource_id: The ID of resource, which may be any type and whose interpretation is left to the owning class. If not provided, a new :class:`Symbol` will be instantiated.
            """
            if instance_limit is not None and len(cls.instances) >= instance_limit:
                # Find a free instance we can use, as indicated by noting that it is released
                for instance in cls.instances:
                    if instance.is_released():
                        instance._released = False
                        return instance
                    
                raise ValueError(f"Unable to allocate resource; instance limit reached for ManagedResource {name} with no released instance found.")
                
            instance = super().__new__(cls, *inst_args, **inst_kwargs)
            instance._released = True
            instance._allocated = False
            
            if resource_id is None:
                instance._resource_id = Symbol()
            else:
                instance._resource_id = resource_id
            
            if allocate: 
                instance.allocate()
                        
        def allocate(self, force=False):
            """
            Allocate the resource by assigning :field:`_resource_id`. If :field:`_resource_id` is a :class:`Symbol`, it is assigned while passing the keyword argument `force`. Otherwise, :class:`TypeError` is thrown, as resource IDs must be instances of :class:`Symbol` to be allocated.
            :param force: The `force` argument passed to the :class:`Symbol` assignment.
            :type force: `bool`
            """
            if isinstance(self._resource_id, Symbol):
                self._resource_id.assign(self.__class__.allocation_index, force=force)
            else:
                raise TypeError(f'Attempted assignment to non-Symbol resource ID.')
            
            self._released = False
            self._allocated = True
            cls.instances.append(instance)
            cls.allocation_index += self.size if use_instance_size and hasattr(self, "size") else 1
            
        def is_released(self):
            """
            :return: `True` if the resource is currently released and available for use or reuse.
            :rtype: `bool`
            """
            return self._released
        
        def is_allocated(self):
            """
            :return: `True` if the resource has been allocated.
            :rtype: `bool`
            """
            return self._allocated

        def release(self):
            """
            Release a resource, allowing it to be reused if the allocation limit of the class is reached.
            """
            self._released = True
            
        cls_attrs = {"instances": [], "allocation_index": 0, "__new__": cls_new, "allocate": allocate, "is_allocated": is_allocated, "is_released": is_released, "release": release, *dct}
        super().__init__(cls, name, bases, cls_attrs)
        
class Processor:
    instruction_set = {}
    
    @classmethod
    def instruction(cls, func):
        """
        A decorator for specifying an instruction belonging to the instruction set of the :class:`Processor`. The provided method is understood to "translate" the associated instruction call and return machine code for the object that will be programmed with these instructions, the exact format of which is left up to the specific derived classes. 
        Calling an instruction method on the :class:`Processor` class itself is understood to express an intent to translate an instruction with provided arguments by calling the underlying function. However, calling the method on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction at that point in the program, meaning that the underlying function should not be called but should simply be added as an entry in the instance's instruction list. This decorator implements this behavior by returning a `classmethod` which will then be automatically bound to the class. Then, the default initializer of this class will iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method, will make a request from the object's . 
        """
        cls.instruction_set.append(func)
        return classmethod(func)
    
    """
    A base class for objects that represent entities capable of being commanded by a set of native "instructions". Native instructions are defined in derived classes by decorating methods that produce their machine code with :meth:`Processor.instruction`.
    Because calling a method decorated with :meth:`instruction` on an instance expresses an intent to command the :class:`Processor` to execute the represented instruction, an entry in the instance's instruction list should be added. This is handled by having trhe initializer iterate through the class' instruction set and bind a new method with the same name to the instance which when called, rather than calling the class method will make a request from the object's :field:`_instructions` ManagedResource. 
    :param instruction_limit: Maximum number of instructions allowed to be called on the :class:`Processor`.
    :type instruction_limit: int
    """
    def __init__(self, instruction_limit=None):
        self.Instruction = ManagedResource(instance_limit=instruction_limit)
        self._instructions = 
        
        # For every instruction, bind a new method to the instance with the name of the instruction
        for instruction in instruction_set:
            def append_instruction(self, *args, **kwargs):
                self.instructions.append({"instruction": instruction, "args": args, *kwargs})
                
            setattr(self, instruction.__name__, MethodType(append_instruction, self))
            
    def __new__(cls, *args, **kwargs)
        """
        Prevents a :class:`Processor` from being directly instantiated. This is typically handled with the `abc` module, but because :class:`Processor` doesn't actually implement any abstract methods, ABCMeta will not prevent :class:`Processor` from being directly instantiated. Therefore, to implement this, we'll just override :meth:`__new__` and fail to return a new object if its class is :class:`Processor`.
        """
        if cls is Processor:
            raise TypeError("Processor cannot be directly instantiated; one must define a subclass.")
        
        super().__new__(cls, *args, **kwargs)