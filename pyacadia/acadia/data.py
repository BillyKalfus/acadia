import os
import json
import pickle
import logging
import fcntl
import operator
import mmap

from functools import reduce
from typing import Tuple
from multiprocessing import Event

import numpy as np
from numpy.lib.format import descr_to_dtype, dtype_to_descr

__all__ = ["RecordGroupMeta", 
           "ArrayRecordGroup",
           "CounterRecordGroup", 
           "DataManager"]

class RecordGroup:
    """
    A group of records to be saved. This class should not be directly 
    instantiated or subclassed; instead, subclasses should be created with the
    metaclass :class:`RecordGroupMeta` in order to create a universal mapping
    between class initializers and their names.
    """
    
    def __init__(self, name, directory, **metadata):
        """
        Create a new record group.
        
        :param name: Group name
        :type name: str
        :param directory: Directory into which group files will be saved or
            loaded
        :type directory: str
        """
        self._name = name
        self._directory = directory
        self._metadata = {"instantiator": self.__class__.__name__, 
                          "count": 0}
        self._metadata.update(metadata)
    
    def load(self, metadata=None):
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
        self._metadata = metadata
    
    def close(self) -> None:
        """
        Close any internally-loaded memory maps or open files.
        """
        pass
    
    def write(self, record) -> None:
        """
        Write a new record to internal storage. Note that this does not save 
        the data in any way, and recoverable storage should be created by 
        calling :meth:`save`.
        """
        pass

    @classmethod
    def file_extension(self) -> str:
        """
        Return the name of the file storing data for this record group.
        """
        return "bin"

    def filename(self) -> str:
        return f"{self._name}.{self.file_extension()}"

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
        return self._metadata
    
    def add_metadata(self, key: str, value) -> None:
        """
        Add an arbitrary piece of metadata to the group to be saved alongside 
        it.
        """
        self._metadata[key] = value
    
    @staticmethod
    def filedeltas(metadata1: dict, metadata2: dict) -> Tuple[int,int]:
        """
        Given two sets of metadata for the group, this method determines 
        which files have changed between the two instants at which the metadata
        objects were generated. This will return a tuple whose
        first element is the offset within the file where changes begin and the 
        second element is the length of changed data. The implementation of
        this behavior will be specific to each subclass, but it must be 
        guaranteed that if the file is copied at
        the time that `metadata1` is produced, then the offset returned by this
        method for the file will be a valid seek location.
        """
        return (0, 0)
    
    def __len__(self) -> int:
        """
        :return: The number of records stored in the group
        :rtype: int
        """
        return self._metadata["count"]
    
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
    CLASSES: dict[str, type] = {}
    
    def __new__(cls, name, bases, dct):
        if name in RecordGroupMeta.CLASSES:
            raise NameError(f"There already exists a class with name {name}")
        
        # Subclass RecordGroup if we haven't already
        has_record_group = False
        for base in bases:
            if issubclass(base, RecordGroup):
                has_record_group = True
                break
            
        new_bases = bases if has_record_group else (RecordGroup, *bases)
        c = super().__new__(cls, name, new_bases, dct)
        RecordGroupMeta.CLASSES[name] = c
        return c
        
class ArrayRecordGroup(metaclass=RecordGroupMeta):
    """
    A collection of similarly-shaped array-like records.
    """
    
    def __init__(self, 
                 name, 
                 directory,
                 dtype=None, 
                 overwrite=False,
                 map=True,
                 **metadata):
        """
        :param name: Name of the group
        :type name: str
        :param dtype: Element datatype
        :type dtype: Any valid input to the constructor of ``numpy.dtype``
        :param axes: Axis specifiers for describing data structure. If 
            ``None``, the record data is interpreted as a one-dimensional list
            of elements. Otherwise, this must be a list where each element
            describes a dimension of the data. These elements may be of various
            types; if an integer, it corresponds to the size of the array along
            that dimension; if a numpy array, it corresponds to axis values for
            that dimension.
        :param append_records: If `True`, new records will be appended to the
            complete record; otherwise, they will overwrite it.
        """
        super().__init__(name, directory, **metadata)
        self._dtype = np.dtype(dtype) if dtype is not None else dtype
        self._records = None
        self._loaded_elements = None
        self._open_objects = []
        self._metadata.update({"descr": None, 
                               "shape": None, 
                               "count": 0, 
                               "overwrite": overwrite,
                               "map": map})
    
    @staticmethod
    def filedeltas(metadata1: dict, metadata2: dict) -> Tuple[int, int]:
        if metadata2 is None or metadata2["descr"] is None:
            return (0, 0)

        dtype = descr_to_dtype(metadata2["descr"])
        size_bytes2 = metadata2["count"]*reduce(operator.mul, metadata2["shape"], dtype.itemsize)
        
        if (metadata1 is None or len(metadata1) == 0 or metadata1["overwrite"]):
            return (0, size_bytes2)
        
        # if ((metadata1["descr"] != metadata2["descr"]) 
        #         or (metadata1["shape"] != metadata2["shape"])):
        #     raise TypeError(f"Descriptor mismatch between metadata:\n"
        #                     f"    metadata1: {metadata1}\n"
        #                     f"    metadata2: {metadata2}")
                
        size_bytes1 = metadata1["count"]*reduce(operator.mul, metadata2["shape"], dtype.itemsize)
        return (size_bytes1, size_bytes2-size_bytes1)

    def write(self, record):
        if hasattr(record, "memory"):
            record = record.memory 
            
        if isinstance(record, np.ndarray):
            if self._dtype is None:
                self._dtype = record.dtype
                self._metadata["descr"] = dtype_to_descr(self._dtype)
                self._metadata["shape"] = record.shape
            elif record.dtype != self._dtype:
                raise TypeError(f"Received numpy array of incorrect dtype"
                                f" (expected {self._dtype}, received array"
                                f" of {record.dtype})")
        elif isinstance(record, (float, int, complex, bool, np.generic)):
            if self._dtype is None:
                self._dtype = np.dtype(type(record))
                self._metadata["descr"] = dtype_to_descr(self._dtype)
                self._metadata["shape"] = tuple()
            record = np.array(record, dtype=self._dtype)
        elif isinstance(record, dict):
            if self._dtype is None:
                fields = [((k, v.dtype, v.shape) if isinstance(v, np.ndarray) else (k, np.dtype(type(v)))) 
                                for k,v in record.items()]
                self._dtype = np.dtype(fields)
                self._metadata["descr"] = dtype_to_descr(self._dtype)
                self._metadata["shape"] = tuple()
            
            record = np.array(tuple(record.values()), dtype=self._dtype)
        else:
            raise TypeError(f"Unable to write record of type {type(record)}"
                            f" into ArrayRecordGroup")

        full_path = os.path.join(self._directory, self.filename())
            
        with open(full_path, ("wb" if self._metadata["overwrite"] else "ab")) as f:
            record.tofile(f)
        
        self._metadata["count"] += 1

    @classmethod
    def file_extension(cls):
        return "bin"

    def load(self, metadata: dict):
        """
        Load records from a file. 
        
        :param metadata: Metadata for stored files, as would be returned by 
            calling :meth:`metadata`
        :type metadata: dict
        :param map: If `True`, data is memory-mapped instead of loaded into 
            memory.
        """
        full_path = os.path.join(self._directory, self.filename())
        
        if not os.path.isfile(full_path):
            logging.error(f"Unable to find array data for {self.filename()} in"
                          f" directory {self._directory}")
            return None
        
        dtype = descr_to_dtype(metadata["descr"])
        record_bytes = reduce(operator.mul, metadata["shape"], dtype.itemsize)
        file_size = os.path.getsize(full_path)
        records = file_size // record_bytes
        leftover_bytes = file_size % record_bytes
        if leftover_bytes != 0:
            logging.warning(f"File {self.filename()} does not contain an integer"
                            f" number of records (file size {file_size}"
                            f" bytes, {records} complete records of dtype"
                            f" {dtype} and shape {metadata['shape']})")
        
        if metadata["map"]:
            file = open(full_path, "rb")
            m = mmap.mmap(file.fileno(), 
                          length=records*record_bytes, 
                          prot=mmap.PROT_READ, 
                          flags=mmap.MAP_SHARED)
            self._open_objects += [m,file]
            self._records = np.ndarray(shape=(records,*metadata["shape"]), dtype=dtype, buffer=m, order='C')
        else:
            self._records = np.fromfile(full_path, 
                              dtype=dtype, 
                              count=records*record_bytes//dtype.itemsize).reshape(records,*metadata["shape"])
            
        self._metadata = metadata
        self._metadata["count"] = records
        self._dtype = dtype
            
    def close(self):
        for obj in self._open_objects:
            obj.close()
        self._open_objects = []
    
    def records(self):
        return self._records
    
    @property
    def shape(self):
        return self._metadata["shape"]
    
    @property
    def dtype(self):
        return self._dtype
    
    @property
    def size(self):
        return self._metadata["count"] * np.prod(self.shape)
    
    @property
    def __array_interface__(self):
        return self._records.__array_interface__
    
    def __array__(self):
        return self._records.__array__()
    
    def __getitem__(self, k):
        return self._records[k]
    
class CounterRecordGroup(metaclass=RecordGroupMeta):
    """
    A simple counter.
    """
    
    def __init__(self, name, directory, **metadata):
        """
        Initialize the reporter with an iterator. Any additional keyword 
        arguments are passed to the constructor for the underlying 
        `ipywidgets.IntProgress` instance.
        """
        super().__init__(name, directory, **metadata)

    def __add__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        return self.count + v

    def __sub__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        return self.count - v

    def __iadd__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        self.count = self.count + v
        return self

    def __isub__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        self.count = self.count - v
        return self

    def __radd__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        return v + self.count

    def __rsub__(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter operation: {type(v)}")
        return v - self.count
        
    @property
    def count(self):
        return self._metadata["count"]
    
    @count.setter
    def count(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter value: {type(v)}")
            
        self._metadata["count"] = v
        
    @property
    def total(self):
        if "total" not in self._metadata:
            return None
        
        return self._metadata["total"]
    
    @total.setter
    def total(self, v):
        if not isinstance(v, int):
            raise TypeError(f"Incompatible type for counter total: {type(v)}")
            
        self._metadata["total"] = v

class PickleRecordGroup(metaclass=RecordGroupMeta):
    """
    A :class:`RecordGroup` for storing arrays of pickled objects.
    """

    def __init__(self, name, directory, overwrite=False, **metadata):
        super().__init__(name, directory, **metadata)
        self._metadata["offsets"] = {}
        self._metadata["size"] = 0
        self._metadata["overwrite"] = overwrite

    @staticmethod
    def filedeltas(metadata1: dict, metadata2: dict) -> Tuple[int, int]:
        if metadata2 is None:
            return (0, 0)
        
        if (metadata1 is None or len(metadata1) == 0 or metadata1["overwrite"]):
            return (0, metadata2["size"])
        
        return (metadata1["size"], metadata2["size"]-metadata2["size"])

    def write(self, record, key=None):
        data = pickle.dumps(record)

        full_path = os.path.join(self._directory, self.filename()) 
        with open(full_path, ("wb" if self._metadata["overwrite"] else "ab")) as f:
            f.seek(self._metadata["size"])
            bytes_written = f.write(data)
        
        if key is None:
            key = f"obj" + str(self._metadata["count"])

        self._metadata["count"] += 1
        self._metadata["offsets"][key] = (self._metadata["size"], bytes_written)
        self._metadata["size"] += bytes_written

    def load(self, metadata: dict):
        """
        Load records from a file. 
        
        :param metadata: Metadata for stored files, as would be returned by 
            calling :meth:`metadata`
        :type metadata: dict
        :param map: If `True`, data is memory-mapped instead of loaded into 
            memory.
        """
        self._metadata = metadata
        
    def __getitem__(self, key):
        full_path = os.path.join(self._directory, self.filename())
        
        if not os.path.isfile(full_path):
            logging.error(f"Unable to find array data for {self.filename()} in"
                          f" directory {self._directory}")
            return None
        
        offset, size = self._metadata["offsets"][key]        
        with open(full_path, "rb") as f:
            f.seek(offset)
            data = f.read(size)

        return pickle.loads(data)
    
    def __setitem__(self, k, v):
        self.write(v, k)
        

class DataManager:
    """
    An abstraction for collecting and storing groups of data records.
    """
        
    def __init__(self, directory, save_count=1):
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
        
    def write(self, group_name, record, **kwargs):
        self._groups[group_name].write(record, **kwargs)
        self._record_count += 1        
        if self._record_count == self._save_count:
            self.save()
            self._record_count = 0
        
    def save(self, groups=None):
        """
        Update metadata and commit data in groups to files.
        
        :param groups: If not `None`, only the groups whose names are in this
            list will be saved. Otherwise, all groups will be saved.
        :type groups: list of str
        """   
        if isinstance(groups, str):
            groups = [groups]
        elif groups is None:
            groups = self._groups.keys()

        # logging.debug("Saving records...")
        metadata_path = os.path.join(self._directory, "metadata.json")
        if os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0:
            with open(metadata_path, "r+") as file:
                fcntl.flock(file, fcntl.LOCK_EX)            
                metadata = json.load(file)
                fcntl.flock(file, fcntl.LOCK_UN)
        else:
            metadata = {}

        metadata.update({name: self._groups[name].metadata() for name in groups})
                                
        logging.debug(f"Saving metadata for groups {list(metadata.keys())}")
        with open(metadata_path, "w") as file:
            fcntl.flock(file, fcntl.LOCK_EX)          
            json.dump(metadata, file)
            fcntl.flock(file, fcntl.LOCK_UN)
        
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
        
        if os.path.getsize(metadata_path) == 0:
            return {}

        with open(metadata_path, "r+") as file:
            # We're not actually going to write to it, but we'll request a
            # write lock in order to guarantee that it's not currently being
            # written to by something else
            fcntl.flock(file, fcntl.LOCK_EX)
            file.seek(0)
            metadata = file.read() if raw else json.load(file)
            fcntl.flock(file, fcntl.LOCK_UN)
            
        return metadata
        
    def load(self, groups=None, reload=False):
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
            if reload and group_name in self._groups:
                # Attempt to reload the group
                self._groups[group_name].close()
                self._groups[group_name].load(metadata[group_name])
            else:
                # Create the group new. If we can't, add_group will throw an error
                instantiator = RecordGroupMeta.CLASSES[metadata[group_name]["instantiator"]]                    
                group = instantiator(group_name, self._directory)
                group.load(metadata[group_name])
                self.add_group(group)
            
    def add_group(self, group: RecordGroup):
        """
        Add a group to be managed.
        
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

    def create_group(self, group_type, group_name, *args, **kwargs):
        if not isinstance(group_type, RecordGroupMeta):
            raise TypeError(f"Expected group type to be a subclass of"
                            f" RecordGroupMeta, got type {group_type}")
        
        group = group_type(group_name, self._directory, *args, **kwargs)
        self.add_group(group)
        return group
        
    def count(self, iter, name="counter"):
        """
        Report iterations through an iterable by creating a CounterRecordGroup
        and automatically increasing it for each item yielded by the iterable.
        If this is called with a name of an existing counter, the counter is 
        reset.
        """
        if isinstance(iter, int):
            iter = range(iter)

        total = len(iter) if hasattr(iter, "__len__") else None
        if name in self:
            counter = self._groups[name]
            if not isinstance(counter, CounterRecordGroup):
                raise TypeError(f"Attemped to count using a non-counter"
                                f" record group (name {name})")
        else:
            counter = self.create_group(CounterRecordGroup, name, total=total)      
        
        counter.count = 0      
        for item in iter:
            yield item
            counter += 1
            self.save(name)
            
    def filedeltas(self, metadata):
        """
        Given a set of metadata, return the filedeltas for any necessary 
        updates.
        """
        if not isinstance(metadata, dict):
            raise TypeError(f"Expected dict for metadata; received {type(metadata)}")
        
        deltas = {}
        for group_name,group_metadata in metadata.items():
            group_class = RecordGroupMeta.CLASSES[group_metadata["instantiator"]]
            
            if group_name in self._groups:
                # if group_class.__name__ != self._groups[group_name].metadata()["instantiator"]:
                #     raise TypeError(f"Cannot resolve filedelta for {group_name}"
                #                     f" (current type {type(self._groups[group_name])},"
                #                     f" received instantiator {group_metadata['instantiator']})")
                current_metadata = self._groups[group_name].metadata()
                filename = self._groups[group_name].filename()
            else:
                current_metadata = {}
                filename = f"{group_name}.{group_class.file_extension()}"
            
            deltas[filename] = group_class.filedeltas(current_metadata, group_metadata)

        return deltas
            
    def __getitem__(self, k) -> RecordGroup:
        return self._groups[k]
    
    def __contains__(self, k) -> bool:
        return k in self._groups
    
    def group_names(self):
        return list(self._groups.keys())
    
    def available(self, *names) -> bool:
        """
        Check whether the provided record group names are contained in this 
        :class:`DataManager` and confirm that records are present in them.
        """
        for name in names:
            if name not in self._groups:
                return False
            if self._groups[name].records() is None:
                return False
            
        return True
    