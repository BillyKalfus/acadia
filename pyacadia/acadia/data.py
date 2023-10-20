import os
import json
import numpy as np
import logging
import fcntl
import struct
import operator
import mmap

from copy import copy
from functools import reduce
from itertools import count
from abc import ABC

from numpy.lib.format import header_data_from_array_1_0, descr_to_dtype
import matplotlib.pyplot as plt

__all__ = ["RecordGroup", 
           "ArrayRecordGroup", 
           "DataManager"]

WRLCK_STRUCT = struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0)
UNLCK_STRUCT = struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0)

class RecordGroup:
    """
    A group of records to be saved. This class should not be directly 
    instantiated or subclassed; instead, subclasses should be created with the
    metaclass :class:`RecordGroupMeta` in order to create a universal mapping
    between class initializers and their names.
    """
    
    def __init__(self, name):
        """
        Create a new record group.
        
        :param name: Group name
        :type name: str
        :param output_dir: Directory into which group files will be saved or
            loaded
        :type output_dir: str
        """
        self._name = name
    
    def save(self, directory):
        """
        Flush the internal record cache to files. 
        """
        pass
    
    def load(self, directory, metadata=None, map=True):
        """
        Load data from files into the internal cache.
        
        :param metadata: Some types will require additional data for loading,
            such as array types or shapes. This is subclass-specific and is
            not required to be accessed.
        :type metadata: dict
        :param map: Indicate that memory-mapped data is preferred, if the 
            class supports it.
        :type map: bool
        """
        pass
    
    def full(self):
        """
        For record groups containing an internal memory, this will determine
        whether the internal memory is full.
        """
        return False
    
    def close(self):
        """
        Close any internally-loaded memory maps or open files.
        """
        pass
    
    def append(self, record) -> None:
        """
        Append a new record to internal storage. Note that this does not save 
        the data in any way, and recoverable storage should be created by 
        calling :meth:`save`.
        
        :param record: Record to append
        """
        pass
    
    def metadata(self) -> dict:
        """
        :return: Metadata for the group. The returned data may be arbitrary
            and specific to the subclass, but should contain sufficient 
            information to reconstruct the instance when passed into 
            :meth:`load`. This may be populated when saving, so the return
            value is not defined if :meth:`save` has not been called 
            previously.
        :rtype: dict
        """
        return {}
    
    def files(self) -> list:
        """
        :return: Lists files created by the group
        :rtype: list
        """
        return []
    
    def __len__(self) -> int:
        """
        :return: The number of records stored in the group
        :rtype: int
        """
        return None

    def initialize_display(self):
        """
        Create and store any internal objects needed to initialize the display.
        The return value of this function will be cached in the display thread
        and passed to :meth:`update_display` when called.
        """
        return None
    
    def update_display(self, init_retvals):
        """
        Update the display objects. The return value of 
        :meth:`initialize_display` will be passed in through `init_retvals`.
        """
        pass
    
class RecordGroupMeta(type):
    """
    A metaclass for creating subclasses of RecordGroup. This is necessary so
    that when :meth:`DataManager.load` attempts to create instances of 
    various record groups, there is a central database mapping class names
    to their classes. Normally Python just does this and we could evaluate the
    class name as a literal in order to construct an object; however, since 
    these constructors are called inside DataManager methods, any custom
    constructors will not be in the namespace.
    """
    CLASSES = {}
    
    def __new__(cls, name, bases, dct):
        if name in RecordGroupMeta.CLASSES:
            raise NameError(f"There already exists a class with name {name}")
        c = super().__new__(cls, name, bases, dct)
        RecordGroupMeta.CLASSES[name] = c
        return c
        
class ArrayRecordGroup(RecordGroup, metaclass=RecordGroupMeta):
    """
    A collection of similarly-shaped array-like records.
    """
    
    def __init__(self, name, cache_size = 10e6, record_axes=None):
        """
        :param cache_size: The maximum size of an internal record cache in 
            bytes. This cache will be flushed either when :meth:`save` is
            called or when it fills up. If an individual record is larger than
            the cache, :meth:`save` will be called every time a new record is
            appended.
        :type cache_size: int
        :param record_axes: Axis values for a given record, to be stored with
            the record group's metadata. This should be a list of 1D arrays, 
            with each 1D array corresponding to a particular dimension of the
            record.
        """
        super().__init__(name)
        self._cache = None
        self._cache_count = 0
        self._cache_size = cache_size
        self._cache_full = False
        
        self._record_axes = record_axes if record_axes is not None else []
        self._metadata = {}
        self._open_objects = []
            
    def metadata(self):
        """
        Retrieve metadata for all record files in the group. 
        
        :return: A `dict` whose keys are file names and whose values are the
            return values of `numpy.lib.format.header_data_from_array_1_0` for
            the arrays backing those files.
        :rtype: dict
        """
        return self._metadata
    
    def files(self):
        return list(self._metadata.keys())
    
    def allocate_cache(self, 
                       record_shape: tuple, 
                       dtype: np.dtype, 
                       cache_size: int = None, 
                       order: str = "C"):
        """
        Allocate the internal cache for a given number of records. If the 
        cache has already been allocated, this will overwrite it. A size
        may be provided to overwrite the size that this instance was 
        initialized with.
        
        :type record_shape: tuple
        :param cache_size: Size of the cache to allocate in bytes
        :type cache_size: int
        """
        # This will mark any existing cache for garbage collection
        self._cache = None
        self._cache_count = None
        
        self._record_shape = record_shape
        
        record_size = reduce(operator.mul, record_shape) * dtype.itemsize
        # Using integer division will round down for us
        num_records = int(cache_size if cache_size is not None else self._cache_size) // record_size 
        if num_records > 0:
            self._cache = np.empty(shape=(num_records, *record_shape), dtype=dtype, order=order)
            self._cache_count = 0
            self._cache_full = False
        
    def save(self, directory):
        # We won't save anything if there's no data to save
        if self._cache is None:
            return
        
        # Write the axes only if they haven't been written yet
        for i,axis in enumerate(self._record_axes):
            filename = f"{self._name}_axis{i}.bin"
            full_path = os.path.join(directory, filename)
            if not os.path.exists(full_path):
                with open(full_path, "wb") as f:
                    axis.tofile(f)
                self._metadata[filename] = header_data_from_array_1_0(axis)
        if self._cache is None:
            logging.info(f"`save` called with no saveable data")
            
        filename = f"{self._name}_records.bin"
        header = header_data_from_array_1_0(self._cache)
        
        if filename in self._metadata:
            # Extend the existing number of records by an amount equal to 
            # what's in the cache
            incr = self._cache_count if self._cache_count is not None else 1
            self._metadata[filename]["shape"] = (self._metadata[filename]["shape"][0] + incr, 
                                                *self._metadata[filename]["shape"][1:])
        else:
            # Create a new entry in the metadata
            # We'll copy all the header information from the cache, but depending
            # on whether we have a cache, we may need to add a dimension to the shape
            self._metadata[filename] = header
            if self._cache_count is None:
                # No cache, add a dimension for number of records
                self._metadata[filename]["shape"] = (1, *self._metadata[filename]["shape"])
            else:
                # Even though the header has an axis for record number,
                # the header will contain the max cache size for this axis
                self._metadata[filename]["shape"] = (self._cache_count, *self._metadata[filename]["shape"][1:])
            
        with open(os.path.join(directory, filename), "ab") as f:
            if self._cache_count is not None:
                self._cache[:self._cache_count].tofile(f)
                self._cache_count = 0
            else:
                self._cache.tofile(f)
                
        self._cache_full = False
            
    def _load_array(self, filename, directory, header_data, map=False):
        full_path = os.path.join(directory, filename)
        
        if not os.path.isfile(full_path):
            logging.debug(f"Unable to find array data for {filename} in"
                          f" directory {directory}")
            return None
        # else:
        #     logging.debug(f"Found file {full_path} ({os.path.getsize(full_path)} bytes)")
        
        if filename not in header_data:
            logging.debug(f"No header for {filename} found")
            return None
        
        # logging.debug(f"{'Mapping' if map else 'Loading'} {full_path} with"
        #               f" header {header_data[filename]}")
        
        
        dtype = descr_to_dtype(header_data[filename]["descr"])
        order = 'F' if header_data[filename]["fortran_order"] else 'C'
        shape = tuple(header_data[filename]["shape"])
        count = reduce(operator.mul, shape)
        size = count*dtype.itemsize
        
        # logging.debug(f"Extracted: dtype {dtype}, order {order}, shape {shape}"
        #               f" ({count} items in {size} bytes)")
        
        if map:
            file = open(full_path, "rb")
            m = mmap.mmap(file.fileno(), length=size, prot=mmap.PROT_READ, flags=mmap.MAP_SHARED)
            self._open_objects += [m,file]
            arr = np.ndarray(shape=shape, dtype=dtype, buffer=m, order=order)
        else:
            arr = np.fromfile(full_path, dtype=dtype, count=count)
            arr = np.reshape(arr, shape, order=order)
            
        return arr
    
    def load(self, directory, metadata=None, map=False):
        """
        Load records from a directory of files. 
        
        :param name: The name of the group data to load
        :type name: str
        :param input_dir: The directory to load group files from
        :type input_dir: str
        :param metadata: Metadata for stored files, as would be returned by 
            calling :meth:`metadata`
        :type header_data: dict
        :param map: If `True`, data is memory-mapped instead of loaded into 
            memory.
        """
        self._cache = self._load_array(f"{self._name}_records.bin", 
                                               directory, 
                                               metadata, 
                                               map)
        
        self._record_axes = []
        for axis_idx in count():
            axis_filename = f"{self._name}_axis{axis_idx}.bin"
            if os.path.exists(os.path.join(directory, axis_filename)):
                axis = self._load_array(axis_filename, directory, metadata, map)
                self._record_axes.append(axis)
            else:
                break
            
    def close(self):
        for obj in self._open_objects:
            obj.close()
        self._open_objects = []
    
    def append(self, record):
        if self._cache is None:
            self.allocate_cache(record.shape, record.dtype)
            
        if self._cache_full:
            raise MemoryError(f"Attempted to append record to group"
                              f" {self._name} with full cache.")
        
        # If the cache is still None, then it was determined that a cache 
        # will be unable to hold a single record
        if self._cache_count is None:
            self._cache = record
            self._cache_full = True
        else:    
            if record.shape != self._record_shape:
                raise ValueError(f"Incompatible record shape (expected"
                                f" {self._record_shape}, received {record.shape})")
                
            self._cache[self._cache_count, ...] = record    
            self._cache_count += 1
            if self._cache_count == self._cache_size:
                self._cache_full = True
            
    def __len__(self):
        return self._cache_count
    
    def records(self):
        return self._cache
    
    def full(self):
        return self._cache_full
    
    def axis(self, idx=0):
        """
        Get the axis for a given dimension.
        
        :param idx: Dimension to get axis for
        :type idx: int
        """
        return self._record_axes[idx]
    
class CounterRecordGroup(RecordGroup, metaclass=RecordGroupMeta):
    """
    A simple counter.
    """
    
    def __init__(self, name="Counter", **widget_kwargs):
        """
        Initialize the reporter with an iterator. Any additional keyword 
        arguments are passed to the constructor for the underlying 
        `ipywidgets.IntProgress` instance.
        """
        super().__init__(name)
        self._total = None
        self._value = None
        self._widget_kwargs = widget_kwargs
        
    def metadata(self):
        return {"total": self._total, "value": self._value}
        
    def load(self, directory, metadata=None, map=True):
        self._total = metadata["total"]
        self._value = metadata["value"]
        
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, v):
        if not isinstance(v, int) and not isinstance(v, float):
            raise TypeError(f"Incompatible type for counter value: {type(v)}")
            
        self._value = v
        
    @property
    def total(self):
        return self._total
    
    @total.setter
    def total(self, v):
        if not isinstance(v, int) and not isinstance(v, float):
            raise TypeError(f"Incompatible type for counter total: {type(v)}")
            
        self._total = v
        
    def initialize_display(self):
        if isinstance(self._value, (int, float)):
            from tqdm.notebook import tqdm
            bar = tqdm(total=self._total, **self._widget_kwargs)
            bar.update(self._value)
        else:
            raise TypeError(f"Incompatible type for progress display:"
                            f" {type(self._value)}")
        return {"bar": bar, "last_value": self._value, "bar_closed": False}
        
    def update_display(self, vals):
        if not vals["bar_closed"]:
            vals["bar"].update(self._value - vals["last_value"])
            vals["last_value"] = self._value
            if self._value == self._total:
                vals["bar"].close()
                vals["bar_closed"] = True

class DataManager:
    """
    An abstraction for collecting and storing groups of data records.
    """
        
    def __init__(self, directory, save_count=5):
        """
        Initializes a DataManager for collecting data records inside a 
        directory. Along with the binary records, a metadata JSON file will be
        used for organizing data records and providing details about their 
        contents. To prevent overloading disk I/O, one can specify how many new
        records should be accepted before saving data by providing a value for
        `save_count`. Data can be manually saved at any time by calling 
        :meth:`save`.
        
        :param directory: Directory into which data will be written.
        :type directory: str
        :param save_count: Specifies how many records should be received before
            saving data to disk and announcing it on the server
        :type save_count: int
        """
        self._directory = directory
        self._save_count = save_count
        self._groups = {}
        self._record_count = 0
        self._progress = {}
        
    def append(self, group_name, record):
        self._groups[group_name].append(record)
        self._record_count += 1        
        if self._record_count == self._save_count:
            self.save()
            self._record_count = 0
        elif self._groups[group_name].full():
            self.save([group_name])
        
    def save(self, groups=None):
        """
        Update metadata and commit data in groups to files.
        
        :param groups: If not `None`, only the groups whose names are in this
            list will be saved. Otherwise, all groups will be saved.
        :type groups: list of str
        """   
        # logging.debug("Saving records...")
        
        metadata = {}
        for name in (groups if groups is not None else self._groups.keys()):   
            group = self._groups[name]                 
            metadata[name] =  {
                "type": group.__class__.__name__,
                "files": group.files(),
                "metadata": group.metadata()
            }

            group.save(self._directory)
                    
        with open(os.path.join(self._directory, "metadata.json"), "a+") as file:
            fcntl.fcntl(file, fcntl.F_SETLKW, copy(WRLCK_STRUCT))            
            file.seek(0)
            file.truncate()
            json.dump(metadata, file)
            fcntl.fcntl(file, fcntl.F_SETLK, copy(UNLCK_STRUCT))
        
        # logging.debug("Saved")
        
    @staticmethod
    def read_metadata(directory, raw=False):
        """
        Read group metadata from a given directory.
        
        :param raw: If `False`, the metadata will be read in with the `json`
            library and converted into the appropriate Python object. 
            Otherwise, the raw file data is returned (as a string).
        :type raw: bool
        """
        metadata_path = os.path.join(directory, "metadata.json")
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"Unable to locate metadata")
        
        with open(metadata_path, "a+") as file:
            # We're not actually going to write to it, but we'll request a
            # write lock in order to guarantee that it's not currently being
            # written to by something else
            fcntl.fcntl(file, fcntl.F_SETLKW, copy(WRLCK_STRUCT))
            file.seek(0)
            metadata = file.read() if raw else json.load(file)
            fcntl.fcntl(file, fcntl.F_SETLK, copy(UNLCK_STRUCT))
            
        return metadata
        
    def load(self, groups=None, map=True, reload=False):
        """
        Map the data stored in an existing directory into the internal 
        structure of the DataManager.
        
        :param map: If `True`, data files will be memory-mapped rather than
            be loaded into memory.
        :type map: bool
        :param groups: If not `None`, this should be a list of group names to
            load. Otherwise, all groups in the metadata will be loaded.
        :type groups: list of str
        :param reload: If `True`, existing records will reloaded from files
        :type reload: bool
        :param extra_initializers: If not `None`, this should be a dict mapping
            group class names to functions that produce them. This is primarily
            useful for adding functions to initialize groups that are not built
            into the package.
        :type extra_initializers: dict
        """
        metadata = DataManager.read_metadata(self._directory)
            
        for group_name in (groups if groups is not None else metadata.keys()):
            for filename in metadata[group_name]["files"]:
                if not os.path.exists(os.path.join(self._directory, filename)):
                    raise FileNotFoundError(f"Unable to locate required file"
                                            f" {filename} in directory"
                                            f" {self._directory}")
                            
            if reload and group_name in self._groups:
                # Attempt to reload the group
                self._groups[group_name].close()
                self._groups[group_name].load(self._directory, 
                        metadata[group_name]["metadata"], 
                        map)
            else:
                # Create the group new. If we can't, add_group will throw an error
                group_class = RecordGroupMeta.CLASSES[metadata[group_name]["type"]]                    
                group = group_class(group_name)
                group.load(self._directory, 
                        metadata[group_name]["metadata"], 
                        map)
                self.add_group(group)
            
    def add_group(self, group: RecordGroup):
        """
        Add a group to be managed with an optional remote preprocessor.
        
        :param name: Name of group
        :type name: str
        :param group: Group to be managed
        :type group: :class:`RecordGroup`
        :param overwrite: If `False`, an Exception will be thrown if one 
            attempts to add a group with the same name.
        :type overwrite: bool
        """
        if group._name in self._groups:
            raise KeyError(f"Group {group._name} already exists.")
        
        if not isinstance(group, RecordGroup):
            raise TypeError("Only `RecordGroup` instances can be added")
        
        self._groups[group._name] = group
        
    def report_iterations(self, iter, name="Iterations", **widget_kwargs):
        """
        Report iterations through an iterable by creating a CounterRecordGroup
        and automatically increasing it for each item yielded by the iterable.
        """
        group = CounterRecordGroup(name, **widget_kwargs)    
        self.add_group(group)
        
        group.value = 0
        group.total = len(iter) if hasattr(iter, "__len__") else None
        
        for item in iter:
            yield item
            group.value += 1
            self.save([name])
            
    def __getitem__(self, k):
        return self._groups[k]
    
    def __contains__(self, k):
        return k in self._groups
    
    def group_names(self):
        return list(self._groups.keys())
                