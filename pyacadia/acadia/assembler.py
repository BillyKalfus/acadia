"""
assembler.py
Assembler for the microarchitecture of the Acadia quantum control system.
William Kalfus, Yale University
December 2022
"""
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
        
class ResourceManager(Operable):
    """
    Metaclass for creating autonomous hardware resource factories. This metaclass implements resource allocation and reuse along with address assignment, and its implementation as a metaclass allows this to occur immediately when instances of derived classes are created. This is a subclass of :class:`Operable`, so that actions on the instances of derived classes can be implemented by inspecting the produced :class:`Operation` objects.
    :param instance_limit: The maximum number of instances that may be created by the class.
    :type instance_limit: int, optional
    :param use_instance_size: If `True`, indicates that the allocation offset should be increased by an amount equal to the provided `size` keyword.  
    :type use_instance_size: bool, optional
    """
    def __new__(cls, name, bases, dct, instance_limit=None, use_instance_size=True):
        
        def cls_new(cls, *inst_args, **inst_kwargs):
            if instance_limit is not None and len(cls.instances) >= instance_limit:
                # Find a free instance we can use, as indicated by noting that it is released
                for instance in cls.instances:
                    if instance.is_released():
                        instance._released = False
                        return instance
                    
                raise ValueError(f"Unable to allocate resource; instance limit reached for ResourceManager {name} with no released instance found.")

            if "resource_id" not in inst_kwargs:
                inst_kwargs["resource_id"] = Symbol(cls.allocation_index) 
            elif isinstance(kwargs["resource_id"], Symbol):
                inst_kwargs["resource_id"].assign(cls.allocation_index)
            else:
                raise TypeError(f'Invalid type for provided instance ID: {inst_kwargs["resource_id"]}')
                
            instance = super().__new__(cls, *inst_args, **inst_kwargs)
            instance._released = False
                        
            cls.instances.append(instance)
            cls.allocation_index += inst_kwargs["size"] if use_instance_size and ("size" in inst_kwargs) else 1
            
        def is_released(self):
            return self._released

        def release(self):
            self._released = True
            
        cls_attrs = {"instances": [], "allocation_index": 0, "__new__": cls_new, "is_released": is_released, "release": release, *dct}
        super().__init__(cls, name, (Resource,*bases), cls_attrs)
        