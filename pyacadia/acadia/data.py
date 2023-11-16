import os
import json
import logging
import fcntl
import struct
import operator
import mmap

from copy import copy
from functools import reduce
from itertools import count

import numpy as np
from numpy.lib.format import header_data_from_array_1_0, descr_to_dtype, dtype_to_descr

__all__ = ["RecordGroupMeta", 
           "ArrayRecordGroup",
           "CounterRecordGroup",
           "PlotMixin",
           "DisplayMixin", 
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
    
    def __init__(self, name, directory):
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
    
    def load(self, metadata=None, map=True):
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
    
    def write(self, record) -> None:
        """
        Write a new record to internal storage. Note that this does not save 
        the data in any way, and recoverable storage should be created by 
        calling :meth:`save`.
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
    
    def add_metadata(self, key, value):
        """
        Add an arbitrary piece of metadata to the group to be saved alongside 
        it.
        """
        raise NotImplemented
    
    def files(self) -> list:
        """
        :return: Lists files created by the group
        :rtype: list
        """
        return []
    
    @staticmethod
    def filedeltas(metadata1, metadata2) -> dict:
        """
        Given two sets of metadata for the group, this method determines 
        which files have changed between the two instants at which the metadata
        objects were generated. For each file, this will return a tuple whose
        first element is the offset within file where changes begin and the 
        second element is the length of changed data. The implementation of
        this behavior will be specific to each subclass, but it must be 
        guaranteed that for all the files with changes, if a file is copied at
        the time that `metadata1` is produced, then the offset returned by this
        method for that file will be a valid seek location for that file.
        """
        return {}
    
    def __len__(self) -> int:
        """
        :return: The number of records stored in the group
        :rtype: int
        """
        return None
    
class DisplayMixin:
    """
    A mixin for :class:`RecordGroup` subclasses that are able to display their
    data visually.
    """

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
    
    def close_display(self, init_retvals):
        """
        Close any open display objects.
        """
        pass
    
class PlotMixin(DisplayMixin):
    
    def plot(self, fig):
        """
        Create plot objects and return a function that will update them.
        Calling this function raises `NotImplementedError`, as this is expected
        to be implemented by the user.
        
        :param fig: The live plot 
        :type fig: matplotlib.Figure
        :return: A function that accepts the animation object and frame number 
            as arguments and sets the data of any updated objects in the figure
        :rtype: callable
        """
        raise NotImplemented(f"No plotting implemented for group {self._name}")
    
    def initialize_display(self):
        import matplotlib.pyplot as plt
        from matplotlib.animation import Animation
        
        fig = plt.figure()
        update_func = self.plot(fig)
        
        def init(anim_self, *args, **kwargs):
            anim_self._framedata = count()
            super(anim_self.__class__, anim_self).__init__(*args, **kwargs)
        
        test_animation_type = type(f"{self._name}Animation", 
                                   (Animation, ), 
                                   {"__init__": init, 
                                    "_draw_frame": update_func})

        def _dummy(*args, **kwargs):
            pass
        
        DummyEvent = type("DummyEvent", (), {"add_callback": _dummy, "start": _dummy, "stop": _dummy})

        
        anim = test_animation_type(fig, event_source=DummyEvent)
        anim._step()

        return anim,fig
    
    def update_display(self, args):        
        anim,fig = args
        anim._step()
        
    def close_display(self, args):
        import io
        import matplotlib.pyplot as plt
        from IPython.display import Image, display
        
        anim,fig = args
        
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=400)
        plt.close("all")
        
        buf.seek(0)
        img = Image(data=buf.read(), format="png", embed=True, width=720)
        display(img)
        
    @staticmethod
    def update_line(plot_retval, xdata, ydata):
        """
        Update the data contained in a line created by calling `Axis.plot`. 
        
        :param plot_retval: Value returned by `plot`
        :type plot_retval: tuple
        """
        plot_retval[0].set_data(xdata, ydata)
        
    @staticmethod
    def update_yerrorbar(errorbar_retval, xdata, ydata, yerr):
        """
        Update the curve and error data on an errorbar.
        """
        ln,err,bars = errorbar_retval
        ln.set_data(xdata, ydata)
        
        new_errorbars = [[[x,ydata[i]-yerr[i]],
                          [x,ydata[i]+yerr[i]]] for i,x in enumerate(xdata)]
        
        bars[0].set_segments([np.array(points) for points in new_errorbars])
    
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
                 axes=None, 
                 overwrite=False):
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
        super().__init__(name, directory)
        self._overwrite = overwrite
        self._dtype = np.dtype(dtype)
        self._records = None
        self._loaded_elements = None
        self._open_objects = []
        self._metadata = {"files": {}, "axes": None, "shape": [], "count": 0}
        
        if axes is not None:
            axis_descriptions = []
            for i,ax in enumerate(axes):
                if isinstance(ax, np.ndarray):
                    filename = f"{self._name}_axis{i}.bin"
                    axis_descriptions.append(filename)
                    self._metadata["shape"].append(len(ax))
                    full_path = os.path.join(self._directory, filename)
                    
                    with open(full_path, "wb") as f:
                        ax.tofile(f)
                        
                    self._metadata["files"][filename] = {
                        "descr": dtype_to_descr(ax.dtype),
                        "length": len(ax),
                        "overwriting": False
                    }
                elif isinstance(ax, int):
                    axis_descriptions.append(ax)
                    self._metadata["shape"].append(ax)
                else:
                    raise TypeError(f"Invalid axis description type {type(ax)}")
        
            self._metadata["axes"] = axis_descriptions
            
    def metadata(self):
        """
        Retrieve metadata for all record files in the group. 
        
        :rtype: dict
        """
        return self._metadata
    
    def files(self):
        return list(self._metadata["files"].keys())
    
    def add_metadata(self, key, value):
        self._metadata[key] = value
    
    @staticmethod
    def filedeltas(metadata1, metadata2):
        deltas = {}
        
        # For every file in metadata2, if it's not contained in metadata1 then
        # return the full size of the file at offset 0. Otherwise, return an
        # offset given by the size of file 1 and a size given by the difference
        # in file sizes
        for filename,file_header2 in metadata2["files"].items():
            dtype = descr_to_dtype(file_header2["descr"])
            size_bytes2 = dtype.itemsize*file_header2["length"]
            
            if (metadata1 is None 
                    or "files" not in metadata1
                    or filename not in metadata1["files"] 
                    or (not metadata1["files"][filename]["overwriting"])):
                deltas[filename] = (0, size_bytes2)
            else:
                if json.dumps(metadata1["files"][filename]["descr"]) != json.dumps(file_header2["descr"]):
                    raise TypeError(f"Descriptor mismatch between metadata for"
                                    f" file {filename}:\n"
                                    f"    metadata1: {metadata1}\n"
                                    f"    metadata2: {metadata2}")
                    
                size_bytes1 = dtype.itemsize*metadata1["files"][filename]["length"]
                deltas[filename] = (size_bytes1, size_bytes2-size_bytes1)

        return deltas
    
    def write(self, record):
        if hasattr(record, "memory"):
            self.write(record.memory())
            return
        
        if isinstance(record, np.ndarray):
            if self._dtype is None:
                self._dtype = record.dtype
            elif record.dtype != self._dtype:
                raise TypeError(f"Received numpy array of incorrect dtype"
                                f" (expected {self._dtype}, received array"
                                f" of {record.dtype})")
        else:
            if self._dtype is None:
                self._dtype = np.dtype(type(record))
            else:
                # A literal, try to create an instance of the dtype from it so
                # that it will throw an error if this fails
                _ = self._dtype(record)

        filename = f"{self._name}_records.bin"
        full_path = os.path.join(self._directory, filename)
        if not os.path.exists(full_path) or self._overwrite:
            self._metadata["files"][filename] = {
                "descr": dtype_to_descr(self._dtype),
                "length": 0,
                "overwriting": self._overwrite
            }
        
        with open(full_path, ("wb" if self._overwrite else "ab")) as f:
            if isinstance(record, np.ndarray):
                record.tofile(f)
                self._metadata["files"][filename]["length"] += len(record)
            else:
                self._dtype(record).tofile(f)
                self._metadata["files"][filename]["length"] += 1
    
            
    def _load_array(self, filename, map=False) -> np.ndarray:
        full_path = os.path.join(self._directory, filename)
        
        if not os.path.isfile(full_path):
            logging.error(f"Unable to find array data for {filename} in"
                          f" directory {self._directory}")
            return None
        
        if "files" not in self._metadata:
            logging.error(f"Incorrect header data format (not 'files' entry found)")
            return None
        
        if filename not in self._metadata["files"]:
            logging.error(f"No header for {filename} found (have"
                          f" {list(self._metadata['files'].keys())})")
            return None
        
        dtype = descr_to_dtype(self._metadata["files"][filename]["descr"])
        count = self._metadata["files"][filename]["length"]
        
        file_size = os.path.getsize(full_path)
        if file_size % dtype.itemsize != 0:
            logging.warning(f"File {filename} does not contain an integer"
                            f" number of elements (file size {file_size}"
                            f" bytes, loading dtype {dtype})")
        
        if map:
            file = open(full_path, "rb")
            m = mmap.mmap(file.fileno(), 
                          length=count*dtype.itemsize, 
                          prot=mmap.PROT_READ, 
                          flags=mmap.MAP_SHARED)
            self._open_objects += [m,file]
            arr = np.ndarray(shape=(count,), dtype=dtype, buffer=m, order='C')
        else:
            arr = np.fromfile(full_path, dtype=dtype, count=count)
            
        return arr
    
    def load(self, metadata=None, map=True):
        """
        Load records from a directory of files. 
        
        :param metadata: Metadata for stored files, as would be returned by 
            calling :meth:`metadata`
        :type header_data: dict
        :param map: If `True`, data is memory-mapped instead of loaded into 
            memory.
        """
        
        # TODO: load the array and potentially apply a shape based on the axes. 
        # potentially add an extra dimension to account for multiple rtecords of the 
        # given shape
        
        self._metadata = metadata
        records_flattened = self._load_array(f"{self._name}_records.bin", map)
        if records_flattened is None:
            # Nothing to load
            return
        
        self._dtype = records_flattened.dtype
        element_count = reduce(operator.mul, metadata["shape"], 1)
        complete_records = len(records_flattened) // element_count
        leftover_elements = len(records_flattened) % element_count
        
        if leftover_elements == 0:
            self._loaded_elements = [complete_records] + [0]*len(metadata["shape"])
            self._records = records_flattened.reshape(tuple([complete_records, *metadata['shape']]))
        else:
            self._loaded_elements = [complete_records] + list(np.unravel_index(leftover_elements, metadata["shape"]))
            self._records = records_flattened
        
        
    def close(self):
        for obj in self._open_objects:
            obj.close()
        self._open_objects = []
    
    def loaded_elements(self):
        """
        Describes how much data has been loaded. Since arrays may not be ragged,
        if the amount of loaded data is not an exact multiple of the number of 
        elements in a record, 
        """
        return self._loaded_elements
    
    def records(self, partial=False):
        """
        Retrieve record data from a loaded record group.
        
        :param partial: If ``True``, all record data is loaded and returned as-is
        :type partial: bool
        """
        if f"{self._name}_records.bin" not in self._metadata["files"]:
            return None
        
        if partial:
            return self._records
        
        elements = self._metadata["files"][f"{self._name}_records.bin"]["length"]
        elements_per_record = reduce(operator.mul, self._metadata["shape"], 1)
        
        if elements < elements_per_record:
            return None
        
        complete_records = elements // elements_per_record
        records_flattened = self._records.flatten()[: complete_records*elements_per_record]
        return records_flattened.reshape(tuple([complete_records, *self._metadata['shape']]))
        
    def axis(self, idx=0, map=False):
        """
        Get the axis for a given dimension. If there are no axes in the group,
        an incrementing array is returned for the single array dimension.
        
        :param idx: Dimension to get axis for
        :type idx: int
        """
        if self._metadata["axes"] is None:
            return np.arange(self._metadata["count"])
        
        if isinstance(self._metadata["axes"][idx], int):
            return np.arange(self._metadata["axes"][idx])
        
        if isinstance(self._metadata["axes"][idx], str):
            return self._load_array(f"{self._name}_axis{idx}.bin", map)
        
        raise TypeError(f"Unable to load axis (metadata contains"
                        f" {self._metadata['axes'][idx]})")

    
class NumericTableRecordGroup(ArrayRecordGroup):
    """
    A record group for storing data arranged in a table. The underlying data
    is encoded in a structured numpy array.
    
    The record can be specified with one of the following formats, after which
    the format must be consistent:
    
    - A tuple, in which names are not assigned and use the numpy default "f0", "f1", etc. names
    - A dict, in which names are given by the keys
    
    In both cases, the type of the argument is inferred.
    """
    
    def __init__(self, 
                 name, 
                 directory,
                 dtype=None, 
                 axes=None, 
                 overwrite=False, 
                 fields=None):
        """
        :param fields: If not `None`, this should be a valid argument to 
            `numpy.dtype` for constructing the data type of the record 
            (see https://numpy.org/doc/stable/reference/arrays.dtypes.html#specifying-and-constructing-data-types 
            for details)
        """
        super().__init__(name, directory, dtype, axes, overwrite)
        self._fields = fields
        
    def write(self, record):
        if isinstance(record, np.ndarray):
            # Act like a regular ArrayRecordGroup
            super().write(record)
            return 
        
        if self._fields is None:
            if isinstance(record, dict):
                self._fields = [((k, v.dtype, v.shape) if isinstance(v, np.ndarray) else (k, np.dtype(type(v)))) 
                                for k,v in record.items()]
            elif isinstance(record, tuple) or isinstance(record, list):
                self._fields = [(('', v.dtype, v.shape) if isinstance(v, np.ndarray) else ('', np.dtype(type(v)))) 
                                for v in record]
            else:
                raise TypeError(f"Unable to get fields from type {type(record)}")
            
        if isinstance(record, dict):
            record_data = tuple(record.values())
        elif isinstance(record, tuple) or isinstance(record, list):
            record_data = tuple(record)
        else:
            raise TypeError(f"Unable to get fields from type {type(record)}")
        
        record_ndarray = np.array([record_data], dtype=np.dtype(self._fields))
        super().write(record_ndarray)
        
    
class CounterRecordGroup(DisplayMixin, metaclass=RecordGroupMeta):
    """
    A simple counter.
    """
    
    def __init__(self, name, directory, **widget_kwargs):
        """
        Initialize the reporter with an iterator. Any additional keyword 
        arguments are passed to the constructor for the underlying 
        `ipywidgets.IntProgress` instance.
        """
        super().__init__(name, directory)
        self._total = None
        self._value = None
        self._widget_kwargs = widget_kwargs
        
    def metadata(self):
        return {"total": self._total, "value": self._value}
        
    def load(self, metadata=None, map=True):
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
            bar = tqdm(total=self._total, desc=self._name, **self._widget_kwargs)
            bar.update(self._value)
        else:
            raise TypeError(f"Incompatible type for progress display:"
                            f" {type(self._value)}")
        return {"bar": bar, "last_value": self._value}
        
    def update_display(self, vals):
        vals["bar"].update(self._value - vals["last_value"])
        vals["last_value"] = self._value
            
    def close_display(self, vals):
        vals["bar"].close()

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
        
    def write(self, group_name, record):
        self._groups[group_name].write(record)
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
        # logging.debug("Saving records...")
        metadata_path = os.path.join(self._directory, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r+") as file:
                fcntl.fcntl(file, fcntl.F_SETLKW, copy(WRLCK_STRUCT))            
                metadata = json.load(file)
                fcntl.fcntl(file, fcntl.F_SETLK, copy(UNLCK_STRUCT))
        else:
            metadata = {}
                
        for name in (groups if groups is not None else self._groups.keys()):   
            group = self._groups[name]                 
            metadata[name] =  {
                "type": group.__class__.__name__,
                "files": group.files(),
                "metadata": group.metadata()
            }
                    
        logging.debug(f"Saving metadata for groups {list(metadata.keys())}")
        with open(metadata_path, "w") as file:
            fcntl.fcntl(file, fcntl.F_SETLKW, copy(WRLCK_STRUCT))            
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
        
        with open(metadata_path, "r+") as file:
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
                self._groups[group_name].load(metadata[group_name]["metadata"], map)
            else:
                # Create the group new. If we can't, add_group will throw an error
                group_class = RecordGroupMeta.CLASSES[metadata[group_name]["type"]]                    
                group = group_class(group_name, self._directory)
                group.load(metadata[group_name]["metadata"], map)
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
        group = CounterRecordGroup(name, self._directory, **widget_kwargs)    
        self.add_group(group)
        
        group.value = 0
        group.total = len(iter) if hasattr(iter, "__len__") else None
        
        for item in iter:
            yield item
            group.value += 1
            self.save([name])
            
    def filedeltas(self, metadata):
        """
        Given a set of metadata, return the filedeltas for any necessary 
        updates.
        """
        if not isinstance(metadata, dict):
            raise TypeError(f"Expected dict for metadata; received {type(metadata)}")
        
        deltas = {}
        for group_name,group_metadata in metadata.items():
            group_class = RecordGroupMeta.CLASSES[group_metadata["type"]]
            
            if group_name in self._groups:
                if group_class != type(self._groups[group_name]):
                    raise TypeError(f"Cannot resolve filedelta for {group_name}"
                                    f" (current type {type(self._groups[group_name])},"
                                    f" received {group_metadata['type']})")
                current_metadata = self._groups[group_name].metadata()
            else:
                current_metadata = {}
            
            deltas.update(group_class.filedeltas(current_metadata, group_metadata["metadata"]))
        return deltas
            
    def __getitem__(self, k):
        return self._groups[k]
    
    def __contains__(self, k):
        return k in self._groups
    
    def group_names(self):
        return list(self._groups.keys())
                