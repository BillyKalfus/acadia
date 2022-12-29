"""
assembler.py
Assembler for the microarchitecture of the Acadia quantum control system.
William Kalfus, Yale University
December 2022
"""
from abc import ABC, abstractmethod
import operator
import functools

class Operable(ABC):
    """
    A generic symbolic object. The primary purpose of this class is simply to encapsulate operations between these objects using :class:`Operation` objects, so that they may either be simplified during assembly or translated.
    """ 
    @abstractmethod
    def solve(self):
        """
        :return: The simplified result associated with this :class:`Operable`. This can mean different things for different child classes of :class:`Operable`, and it is the responsibility of calling functions to ensure that the result of calling `solve` is of the correct type before using it.
        """
        pass
    
    @abstractmethod
    def solvable(self):
        """
        :return: `True` if this object is ready to be fully simplified into its final form. As with `solve`, this can mean different things for different child classes, and it is the responsibility of the caller to check the type of the :class:`Operable` before interpreting the return value.
        :rtype: bool
        """
        pass
    
    def __add__(self, other):
        return Operation("add", self, other)

    def __sub__(self, other):
        return Operation("sub", self, other)
    
    def __and__(self, other):
        return Operation("and_", self, other)
    
    def __or__(self, other):
        return Operation("or_", self, other)
    
    def __xor__(self, other):
        return Operation("xor", self, other)
    
    def __lshift__(self, other):
        return Operation("lshift", self, other)
    
    def __rshift__(self, other):
        return Operation("rshift", self, other)
    
    def __inv__(self):
        return Operation("inv", self)
    
    def __neg__(self):
        return Operation("neg", self)
    
    def __not__(self):
        return Operation("not_", self)
    
    def __getattr__(self, attr):
        return Operation("getattr", self, attr=attr)
    
    def __setattr__(self, attr, value):
        return Operation("setattr", self, attr=attr, value=value)
    
    def __getitem__(self, key):
        return Operation("getitem", self, key=key)
    
    def __setitem__(self, key, value):
        return Operation("setitem", self, key=key, value=value)
    
class Operation(Operable):
    """
    A class encapsulating unary or binary operations to be performed on :class:`Operable` objects which are solved by calling the function on the provided arguments.
    :param func: The function to operate on the provided arguments. There is no inherent restriction on the type of this argument, except that it must be interpretable by the underlying types. 
    """
    def __init__(self, func, *args, **kwargs):
        if len(args) > 2:
            raise ValueError("Operation objects may only be used to represent unary or binary operations.")
        if len(args) == 0:
            raise ValueError("At least one positional argument must be provided to the Operation.")
            
        self._func = func
        self._args = args
        self._kwargs = kwargs
        
    def __repr__(self):
        return f"Operation({*args}, {*kwargs})"
    
    def solvable(self):
        """
        Checks all captured arguments to determine solvability. Assumes that all arguments that are not of type :class:`Operable` are solvable.
        :return: `True` if the :class:`Operation` is determined to be solvable.
        :rtype: bool
        """
        for a in self._args:
            if isinstance(a, Operable) and not a.solvable():
                return False
        for k,v in self._kwargs.items():
            if isinstance(v, Operable) and not v.solvable():
                return False
        return True
    
    def solve(self):
        """
        Fully simplify the operation. If the provided function is a callable, it is called on the provided arguments after recursively solving all captured objects of type :class:`Operable`. Otherwise, it checks to see whether the class of the first argument defines a function whose name is the string stored in `self._func`. Note that it does NOT use `hasattr`, as this would potentially recursively create :class:`Operation` objects, but instead looks directly in the defined methods in the class of the first argument. If no corresponding function is found, `TypeError` is raised.
        :return: The simplified operation.
        """
        solved_args = [a.solve() for a in self._args if isinstance(a, Operable) else a]
        solved_kwargs = {k:v.solve() for k,v in self._kwargs.items() if isinstance(v, Operable) else k:v}
        
        if callable(self._func):
            return self._func(*solved_args, *solved_kwargs)
        elif self._func in solved_args[0].__class__.__dict__:
            func = getattr(solved_args[0], self._func)
            return func(*solved_args, *solved_keywords)
        
        raise TypeError(f"Unable to solve: {self}") 
    
class Symbol(Operable):
    """
    Represents a symbolic variable. This allows objects to be distributed that depend on the future decisions of the assembler, such as memory locations or array lengths. In such a situation, this object acts as a placeholder for the desired quantity, to be replaced during translation with the desired value. Note that usage is not restricted to numerical values, and may be defined for any type of object.
    :param value: The value associated with this object. If not provided, may be assigned by the compiler.
    :type value: object, optional
    """
    def __init__(self, value=None):
        self._value = value
        self._assigned = value != None
        
    def assign(self, v, force=False):
        if self.assigned() and not force:
            raise ValueError("Attempted reassignment of Symbol. If you're sure that this is the correct operation, pass force=True.")
            
        self._assigned = True
        self._value = v
        
    def assigned(self):
        """
        Indicates whether the Symbol is assigned.
        :return: True is the Symbol is assigned, otherwise False
        :rtype: bool
        """
        return self._assigned
    
    def solve(self):
        """
        :return: If assigned, returns the value of the :class:`Symbol`. Otherwise returns itself.
        """
        if not self._assigned:
            return self
        return self._value
    
    def solvable(self):
        if isinstance(self._value, Operable):
            return self._value.solvable()
        
        return self.assigned()
    
class Processor(ABC):
    """
    Represents a collection of interconnected hardware resources and a set of function calls allowing them to interact with one another. We call this object a "processor" because typically, these function calls will convert into one or more instructions for an actual processor. 
    """
    main: ResourceManager
    
    def call(self, func, *args, **kwargs):
        """
        Allocate a `dict` encapsulating a native function call on the :class:`Processor` and any associated arguments into the main instruction Resource.
        :param func: Function to be called. If this argument is a string, then the string should represent the name of the corresponding translation method defined for the :class:`Processor` this function is being called on.
        :type func: object
        """
        return main.allocate(data={"func": func, "args": args, *kwargs})
        
    def subroutine(self, func):
        """
        A decorator for indicating that calls to this :class:`Processor` object's `call` method inside of the wrapped function should not be added to the default function call list, but rather are part of an isolated region of instructions typically referred to as a "subroutine". The exact meaning of this (and the corresponding behavior) is left to the child class to define.
        """
    
class Resource(object):
    """
    A reference to a hardware resource, potentially allowing :class:`Symbol` objects representing allocated locations to be assigned at invocation. This is mainly intended to be a bookkeeping and intent-expressing object; since :class:`Symbol` is simply a numeric value, in general more information will be needed to fully express the intent of an action that acts on one or more :class:`Symbol` objects. For example, the address of a particular location in memory doesn't provide any information about what the location represents, what kind of memory it resides in, how interactions with it must be performed, etc. All of these may be resolved by conditioning the action of the host :class:`Processor` on the type of the :class:`Resource` argument.
    Additionally, this provides a mechanism for converting code executed on a resource into function calls on its respective host :class:`Processor`.
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
        
    
        
class ResourceManager(object):
    """
    Creates and tracks :class:`Resource` objects for a particular :class:`Processor`. This allows automatic hardware resource management at compile time by assigning the `symbol` field of the created :class:`Resource` objects upon instantiation. This also allows one to define how multiple different :class:`Processor` objects might access a particular :class:`Resource`, if possible. Optionally, the created objects may be allocated with data, in which case `__setitem__` is automatically called on the created :class:`Resource` with the key "data".
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
    :param dataless: Indicates that the :class:`Resource` objects produced by this class are not capable of storing initialization data.
    """
    def __init__(self, name, host, instance_limit=None, reusable=True, use_instance_size=True, allocation_offset=0, dataless=False, **kwargs):
        if (not hasattr(host, "resource_setitem")) and (not dataless):
            raise NotImplementedError("A host without a resource_setitem method may only store dataless Resources.")
        
        self._type = type(f"{name}Resource", (Resource,), {"_manager": self, "_host": host, *kwargs})
        self._instances = []
        self._dataless = dataless
        self._instance_limit = instance_limit
        self._allocation_offset = allocation_offset
        self._reusable = reusable
        self._use_instance_size = use_instance_size
        self._host = host
        
    def __call__(self, data=None, *args, **kwargs):
        return self.allocate(data, *args, *kwargs)
    
    def allocate(self, data=None, *args, **kwargs):
        """
        Allocate one :class:`Resource` instance with optional associated data.
        :param data: Object to be stored by this :class:`ResourceManager` along with the allocated :class:`Resource`, whose use is defined by the child class.
        :type data: object, optional
        :return: Allocated :class:`Resource`
        :rtype: :class:`Resource`
        """
        if self._dataless and data is not None:
            raise ValueError("Data provided for a Resource unable to store it.")
            
        # We've allocated all the objects we can
        if self._instance_limit is not None and len(self._instances) >= self._instance_limit:
            if not self._reusable:
                raise ValueError(f"Unable to allocate resource; instance limit for non-reusable ResourceManager {self._name} reached.")
            # Loop through and find a free Resource we can use
            for instance in self._instances:
                if instance._released:
                    # We found one, store some new data in it
                    if not self._dataless:
                        instance["data"] = data
                    instance._released = False
                    return instance
            raise ValueError(f"Unable to allocate resource; instance limit reached for ResourceManager {self._name} with no released instance found.")
        
        if "symbol" not in kwargs:
            kwargs["symbol"] = Symbol(self._allocation_offset)
        self._allocation_offset += kwargs["size"] if self._use_instance_size and ("size" in kwargs) else 1
        
        instance = self._type(*args, *kwargs)
        self._instances.append(instance)
        
        if not self._dataless:
            instance["data"] = data
        
        return instance 
