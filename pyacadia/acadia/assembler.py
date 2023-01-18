"""
Assembler for the microarchitecture of the Acadia quantum control system.
"""

__all__ = ["Operable", 
           "Operation", 
           "Symbol", 
           "ManagedResource"]

from types import MethodType
from abc import ABC
from operator import and_

class Operable(type):
    """
    A metaclass used to capture operators acting on instances of derived 
    classes and return a symbolic representation of the operator call.
    """
    
    OPERATORS = ["eq", "ne", "gt", "lt", "ge", "le", 
                 "neg", "abs", "invert",
                 "add", "radd", "iadd", 
                 "sub", "rsub", "isub", 
                 "mul", "rmul", "imul",
                 "floordiv", "rfloordiv", "ifloordiv",
                 "truediv", "rtruediv", "itruediv", 
                 "mod", "rmod","imod", 
                 "pow", "rpow", "ipow", 
                 "lshift", "rlshift", "ilshift",
                 "rshift", "rrshift", "irshift", 
                 "and", "rand", "iand", 
                 "or", "ror", "ior", 
                 "xor", "rxor", "ixor", 
                 "bool", "len",  
                 "iter", "getitem", "setitem", "call", "contains",]
    
    @staticmethod
    def make_op_func(op):
        """
        A function factory for creating functions for operator calls. This is
        mainly necessary because if we try to loop through the list of 
        operators in __new__ like this:
        
        ```
        for op in supported_operators:
            def op_func(*args, **kwargs):
                return Operation(op, *args, **kwargs)
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
            return Operation(op, *args, **kwargs)
        return op_func
     
    def __new__(cls, name, bases, dct):
        supported_operators = dct["OPERATORS"] if "OPERATORS" in dct else Operable.OPERATORS
        for op in supported_operators:
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
    """
    def __init__(self, op, *args, **kwargs):  
        self._op = op
        self._args = args
        self._kwargs = kwargs
        
    def __str__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
    def __repr__(self):
        return f"Operation({self._op}, {self._args}, {self._kwargs})"
    
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
    """
    def __init__(self, value=None):
        self._value = value
        self._assigned = value != None
                
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
        
    def __str__(self):
        return f"Symbol(assigned={self._assigned}, value={self._value})"
    
    def __repr__(self):
        return str(self)
    
    @property
    def value(self):
        if not Symbol.assigned(self):
            raise ValueError("Attempted access of an unassigned Symbol.")
        return self._value
    
    @staticmethod
    def assigned(obj):
        """
        Analyzes the provided object to determine whether all encapsulated 
        :class:`Symbol` objects are assigned. It evaluates :class:`Operation` 
        objects by recursively checking on their arguments, and it evaluates 
        :class:`Symbol` objects by checking whether they are assigned. All 
        other objects are assumed to be assigned by default.
        
        :param obj: Object to check for assignment.
        """
        if isinstance(obj, Operation):
            return reduce(and_, map(Symbol.assigned, obj._args + [v for k,v in obj._kwargs.items()]))
        elif isinstance(obj, Symbol):
            return obj._assigned and Symbol.assigned(obj._value)
        return True
        
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
    
    :param use_instance_size: If `True`, indicates that the allocation 
    offset should be increased by an amount equal to the provided `size` keyword.  
    
    :type use_instance_size: bool, optional
    """
    def __new__(
        cls_meta_new,
        name_meta_new,
        bases_meta_new,
        dct_meta_new,
        instance_limit=None,
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
            if instance_limit is not None and len(cls.instances) >= instance_limit:
                # Find a free instance we can use, as indicated by noting that it is released
                for instance in cls.instances:
                    if instance._released:
                        instance._released = False
                        return instance
                    
                raise ValueError(f"Unable to allocate resource; instance limit reached for {cls} with no released instance found.")
            resource_id = inst_kwargs.pop("resource_id", None)
            
            instance = super(cls, cls).__new__(cls)
            instance._released = False
            instance._resource_id = Symbol() if resource_id is None else resource_id
            
            if isinstance(resource_id, Symbol) and not Symbol.assigned(resource_id):
                instance._resource_id.assign(cls._allocation_index)
            
            cls._allocation_index += inst_kwargs["size"] if use_instance_size else 1
            cls.instances.append(instance)
            
            return instance
        
        def _insert(cls, res, before=None, reallocate=True):
            """
            Insert a resource before a specified resource in the instance list.
            If no resource is specified to determine the insertion location, 
            the resource to be inserted is removed from its current location 
            and appended to the end.
            
            :param res: Resource to insert
            
            :param before: Resource before which to insert `res`
            """
            cls.instances.remove(res)
            cls.instances.insert(cls.instances.index(before) if before is not None else len(cls.instances), res)
            
            cls._allocation_index = 0
            for instance in cls.instances:
                instance._allocate(force=True)
        
        attrs = {"instances": [],
                 "__new__": cls_new,
                 "_allocation_index": 0,
                 "_insert": classmethod(_insert),
                **dct_meta_new}

        new_cls = super().__new__(cls_meta_new, name_meta_new, bases_meta_new, attrs)
        return new_cls
        
