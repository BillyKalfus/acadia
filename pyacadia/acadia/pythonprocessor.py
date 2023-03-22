"""
A set of classes defining the interface for abstractions of hardware
processors.
"""

__all__ = ["PythonProcessor"]

import operator
from dataclasses import dataclass
from numbers import Number
from types import FunctionType
from contextlib import contextmanager

from .compiler import Operation, Symbol, ManagedResource, Processor, ProcessorSubroutineMixin

class PythonProcessorCacheable:
    """
    A mixin for designating custom classes as being able to be cached in a 
    :class:`PythonProcessor`'s cache.
    """
    pass

@dataclass(repr=False)
class PythonProcessorName:
    """
    A wrapper for strings to indicate that they represent direct text to be
    inserted.
    """
    wrapped: str
    
    def __repr__(self):
        return self.wrapped
    
class PythonProcessor(Processor, ProcessorSubroutineMixin):
    """
    A processor capable of executing Python commands. For this 
    :class:`Processor`, compiling consists of generating strings containing
    Python code and assembly consists of calling the Python compiler on it.
    """
    
    def __init__(self):
        super().__init__()
        
        # Create a ManagedResource for keeping track of imports and allowing
        # their members to be called
        def import_init(import_self, lib_name):
            import_self._lib_name = lib_name
            self(Operation("import", lib_name))
            
        def import_getattr(import_self, attr):
            return Operation("getattr", 
                             PythonProcessorName(import_self._lib_name), 
                             attr)
                
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
        
        if len(instruction_resource.args) == 0:
            raise ValueError("At least one positional argument must be supplied"
                             " in order to specify the operation being performed.")
            
        op = instruction_resource.args[0]
        compiled_kwargs = {k: self.compile_arg(v) for k,v in instruction_resource.kwargs.items()}
        
        # Create a list containing the lines of Python
        if isinstance(op, str):
            line_list = [op]
        elif isinstance(op, Operation):
            compiled_op = self.compile_arg(op)
            line_list = compiled_op if isinstance(compiled_op, list) else [compiled_op]
        else:
            raise TypeError(f"Operation of incompatible type ({type(op)}): {op}")
        
        # Indent the lines while formatting the lines with any kwargs
        indent = "    "*instruction_resource.inline_block_level
        if len(compiled_kwargs) > 0:
            indented_lines = [indent + line.format(**compiled_kwargs) for line in line_list]
        else:
            indented_lines = [indent + line for line in line_list]
            
        # Assign the compiled lines to the instruction resource
        instruction_resource.compiled = indented_lines
        
    def call(self, *args, **kwargs):
        """
        Create an :class:`Operation` to call a function on the PythonProcessor.
        """
        return Operation("call", *args, **kwargs)
    
    def call_subroutine(self, instruction_resource):
        """
        Implement subroutine calls by extracting the function from the
        :class:`PythonProcessor` instance at runtime, along with the arguments.
        """
        instruction_instance = f"self.Instruction.instances[{instruction_resource._resource_id}]"
        code_string = (f"self._subroutines[{instruction_resource.name}]"
                       f"(*({instruction_instance}[\'args\']), "
                       f"**({instruction_instance}[\'kwargs\']))")
        return [code_string]
    
    # Some helper functions for use during compilation
        
    def compile_cached_object(self, obj):
        """
        Stores an object in this instance's data cache and returns a compiled
        statement that will retrieve it at runtime. The provided argument must
        have an entry in this class' `cacheable_types` dictionary.
        """
        cache_key = f"_cached_object{len(self._data)}"
        
        if isinstance(obj, Symbol):
            object_retrieval_string = f"self._data['{cache_key}'].value"            
        elif (isinstance(obj, range) 
              or isinstance(obj, list) 
              or isinstance(obj, FunctionType) 
              or isinstance(obj, bytes) 
              or isinstance(obj, slice) 
              or isinstance(obj, type)
              or isinstance(obj, PythonProcessorCacheable)
              or isinstance(type(obj), ManagedResource)):
            object_retrieval_string = f"self._data['{cache_key}']"
        else:
            raise TypeError(f"Unable to cache object {obj} (type {type(obj)}).")
            
        self._data[cache_key] = obj    
        return object_retrieval_string
        
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
        
        if isinstance(obj, PythonProcessorName):
            # A name to be directly inserted
            return f"{obj}"
        
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
                
            obj = self.compile_arg(operation._args[0])
            return f"{obj}.{operation._args[1]}"
        
        if operation._op == "setattr":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"A setattr Operation must have exactly three positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            obj = self.compile_arg(operation._args[0])
            translated_value = self.compile_arg(operation._args[2])
            return f"setattr({obj}, \"{operation._args[1]}\", {translated_value})"
        
        if operation._op == "getitem":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"A getitem Operation must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            obj = self.compile_arg(operation._args[0])
            translated_key = self.compile_arg(operation._args[1])
            return f"{obj}[{translated_key}]"
        
        if operation._op == "setitem":
            if len(operation._args) != 3 or len(operation._kwargs) != 0:
                raise ValueError(f"A setitem Operation must have exactly three positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            obj = self.compile_arg(operation._args[0])
            translated_key = self.compile_arg(operation._args[1])
            translated_value = self.compile_arg(operation._args[2])
            return f"{obj}[{translated_key}] = {translated_value}"
        
        if operation._op == "getdata":
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError(f"A getdata Operation must have exactly one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            translated_key = self.compile_arg(operation._args[0])
            return f"self._data[{translated_key}]"
        
        if operation._op == "setdata":
            if len(operation._args) != 2 or len(operation._kwargs) != 0:
                raise ValueError(f"A setdata Operation must have exactly two positional arguments"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            translated_key = self.compile_arg(operation._args[0])
            translated_value = self.compile_arg(operation._args[1])
            return f"self._data[{translated_key}] = {translated_value}"
        
        if operation._op in ["neg", "abs", "invert"]:
            # Unary operators
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError(f"A {operation._op} Operation must have exactly one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_arg = self.compile_arg(operation._args[0])
            return f"operator.__{operation._op}__({compiled_arg})"
        
        if operation._op in ["bool", "int", "str", "float", "complex"]:
            # Conversion functions
            if len(operation._args) != 1 or len(operation._kwargs) != 0:
                raise ValueError(f"A {operation._op} Operation must have exactly one positional argument"
                                 f" (got args={operation._args}, kwargs={operation._kwargs}).")
            compiled_arg = self.compile_arg(operation._args[0])
            return f"{operation._op}({compiled_arg})"
        
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
            return f"operator.__{operation._op[1:]}__({compiled_args[1]}, {compiled_args[0]})"
        
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

        raise ValueError(f"Unable to compile operation {operation._op} with"
                         f" args={operation._args}, kwargs={operation._kwargs}.")
        
    # Add some macros for accessing the processor data

    def __getitem__(self, key):
        """
        Access a Python object in the namespace of the compiled program.
        """
        return Operation("getdata", key)
        
    def __setitem__(self, key, value):
        """
        Assign a value to a Python variable in the namespace of the compiled 
        program.
        
        :param key: Name of the variable to be assigned.
        :type key: `str`
        :param value: The value to assign to the variable
        """
        return self(Operation("setdata", key, value))
    
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
    
    def run(self, assembled=True):
        """
        This function executes the internally-stored program. This is expected 
        to be called on the hardware running the Python environment that the 
        program targets.
        :param assembled: If `True`, runs the pre-assembled program. Otherwise,
        the compiled program is run line by line.
        :type assembled: bool, optional
        """
        if assembled:
            exec(self._assembled_program)
        else:
            for line in self._compiled_program:
                exec(line)
        
            
    