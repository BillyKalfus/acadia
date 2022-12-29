"""
acadia.py
Assembler for the microarchitecture of the Acadia quantum control system.
William Kalfus, Yale University
December 2022
"""
import numpy as np
import operator
import functools

###### Assembler Objects #######

class Symbol(object):
    """
    Represents a generalized numerical value known to the assembler, but not necessarily the user. This allows numbers to be embedded into :class:`Processor` function calls that depend on the decisions of the assembler, such as memory locations or array lengths. In such a situation, the :class:`Symbol` acts as a placeholder for the desired quantity, to be replaced during assembly with the desired value. 
    :param value: The value associated with this object. If not provided, may be assigned by the compiler.
    :type value: object, optional
    """
    def __init__(self, value=None):
        self._value = value
        self._assigned = value != None
        
    @property
    def value(self):
        """
        :return: the value of the Symbol
        :raises: ValueError, when the Symbol is not yet assigned
        """
        if not self._assigned:
            raise ValueError("Attempted access of an unassigned Symbol.")
        return self._value
        
    @value.setter
    def value(self, v):
        self._assigned = True
        self._value = v
        
    @property
    def assigned(self):
        """
        Indicates whether the Symbol is assigned.
        :return: True is the Symbol is assigned, otherwise False
        :rtype: bool
        """
        return self._assigned
    
    def __add__(self, other):
        return SymbolOperation(operator.add, self, other)

    def __sub__(self, other):
        return SymbolOperation(operator.sub, self, other)
    
    def __and__(self, other):
        return SymbolOperation(operator.and_, self, other)
    
    def __or__(self, other):
        return SymbolOperation(operator.or_, self, other)
    
    def __xor__(self, other):
        return SymbolOperation(operator.xor, self, other)
    
    def __lshift__(self, other):
        return SymbolOperation(operator.lshift, self, other)
    
    def __rshift__(self, other):
        return SymbolOperation(operator.rshift, self, other)
    
    def __inv__(self):
        return SymbolOperation(operator.inv, self)
    
    def __neg__(self):
        return SymbolOperation(operator.neg, self)
    
    def __not__(self):
        return SymbolOperation(operator.not_, self)
    
class SymbolOperation(Symbol):
    """
    Represents an operation acting on a Symbol or set of Symbols, to be evaluated after the Symbols have been assigned values. 
    :param func: Function operating on the provided Symbol operations. Must be able to accept as many arguments as provided to the remainder of the constructor and return a type which may be casted to np.uint32.
    :type func: callable returning a type able to be casted to int
    """
    def __init__(self, func, *args):
        self._func = func
        self._args = args
        Symbol.__init__(self)

    @property
    def value(self):
        if not self.assigned:
            raise ValueError("Attempted access of a SymbolOperation containing unassigned Symbol(s).")
                
        return self._func(*[arg.value if isinstance(arg, Symbol) else arg for arg in self._args])
    
    @property
    def assigned(self):
        """
        Determines whether the SymbolOperation will produce a definite value by checking the assignment of all arguments.
        """
        a = True
        for arg in self._args:
            if isinstance(arg, Symbol) and not arg.assigned:
                a = False
                break
        return a 
    
class Resource(object):
    """
    A reference to a hardware resource, potentially allowing :class:`Symbol` objects representing allocated locations to be assigned at invocation. This is mainly intended to be a bookkeeping and intent-expressing object; since :class:`Symbol` is simply a numeric value, in general more information will be needed to fully express the intent of an action that needs a :class:`Symbol`. For example, the address of a particular location in memory doesn't provide any information about what the location represents, what kind of memory it resides in, how interactions with it must be performed, etc. All of these may be resolved by conditioning the action of the host :class:`Processor` on the type of the :class:`Resource` argument.
    "class:`Resource` objects are not intended to be directly instantiated, but should instead be created by :class:`ResourceManager` objects.
    :param symbol: A :class:`Symbol` with which to instantiate the object; if one is not provided, an unassigned :class:`Symbol` will be created.
    :type symbol: :class:`Symbol`, optional
    """
    def __init__(self, symbol=None):
        if symbol is None:
            self._symbol = Symbol()
        else:
            self._symbol = symbol
        self._released = False
        
    def release(self):
        """
        Releases the object for potential reuse.
        """
        self._released = True
        
    def __getattr__(self, attr):
        """
        Overrides the default behavior so that any functions called on the :class:`Resource` are automatically converted into calls on the host :class:`Processor`.
        """
        return functools.partial(self._manager._host.call, func="getattr", key=key)
    
    def __setattr__(self, attr, value):
        return self._manager._host.call(func="setattr", attr=attr, value=value)
    
    def __getitem__(self, key):
        return self._manager._host.call(func="getitem", key=key)
    
    def __setitem__(self, key, value):
        return self._manager._host.call(func="setitem", key=key, value=value)
        
class ResourceManager(object):
    """
    Creates and tracks :class:`Resource` objects for a particular :class:`Processor`. This allows automatic hardware resource management at compile time, and the `symbol` field of the created `Resource` objects will be assigned at instantiation. This also allows one to define how multiple different :class:`Processor` objects might access a particular :class:`Resource`, if possible.
    :param name: The name of the new type of object to be created by this class.
    :type name: str
    :param host: The host :class:`Processor` responsible for acting on the hardware represented by the instantiated :class:`Resource` objects.
    :type host: :class:`Processor`
    :param instance_limit: The maximum number of `Resource` objects that may be created by this class.
    :type instance_limit: int, optional
    :param reusable: If `True`, this indicates that when the number of instantiated :class:`Resource` objects equals `instance_limit`, the existing instances should be checked to see whether they were released and if so, they may be reused. When an instance is reused, its :class:`Symbol` value is not reassigned.
    :type reusable: bool, optional
    :param use_instance_size: If `True`, indicates that the allocation offset should be increased by an amount equal to the provided `size` keyword. Otherwise, the :class:`Symbol` 
    :type use_instance_size: bool, optional
    :param allocation_offset: The starting value that this object will use to assign values to :class:`Symbol` objects
    :type allocation_offset: int, optional
    """
    def __init__(self, name, host, instance_limit=None, reusable=True, use_instance_size=True, allocation_offset=0, **kwargs):
        self._type = type(f"{name}Resource", (Resource,), {"_manager": self, *kwargs})
        self._instances = []
        self._instance_limit = instance_limit
        self._allocation_offset = allocation_offset
        self._reusable = reusable
        self._use_instance_size = use_instance_size
        self._host = host
        
    def __call__(self, *args, **kwargs):
        if self._instance_limit is not None and len(self._instances) >= self._instance_limit:
            if not self._reusable:
                raise ValueError(f"Unable to allocate resource; instance limit for non-reusable ResourceManager {self._name} reached.")
            for instance in self._instances:
                if instance._released:
                    instance._released = False
                    return instance
            raise ValueError(f"Unable to allocate resource; instance limit reached for ResourceManager {self._name} with no released instance found.")
        
        if "symbol" not in kwargs:
            kwargs["symbol"] = Symbol(self._allocation_offset)
        self._allocation_offset += kwargs["size"] if self._use_instance_size and ("size" in kwargs) else 1
        
        instance = self._type(*args, *kwargs)
        self._instances.append(instance)
        return instance        
        
