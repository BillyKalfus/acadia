import os
import datetime
import shutil
import json
import pickle
import numpy as np
import io
import logging
import socket

from abc import ABC, abstractstaticmethod, abstractmethod
from threading import Thread, Event, Lock

__all__ = ["RecordGroup", 
           "ListRecordGroup", 
           "ArrayRecordGroup", 
           "DataManager", 
           "Plotter"]


class RecordGroup(ABC):
    """
    A group of records to be saved.
    """
    
    @abstractmethod
    def serialize(self):
        pass
    
    @abstractstaticmethod
    def load(inpt, preprocessor):
        pass
    
    def __getitem__(self, k):
        return self._records[k]
        
    def data(self):
        return self._records
    
    def __len__(self):
        return len(self._records)
    
    def append(self, record):
        pass
    
    def metadata(self):
        return None

class ListRecordGroup(RecordGroup):
    """
    A collection of records stored in a list.
    """
    
    def __init__(self, records=None):
        self._records = records if records is not None else []
        super().__init__()
        
    def serialize(self, output_file):
        """
        Serialize the record into a file.
        
        :param output_file: File-like object to serialize into
        """
        pickle.dump(self._records, output_file)
        
    @staticmethod
    def load(inpt, preprocessor=None):
        """
        Load records from a file or bytes with an optional preprocessing stage.
        
        :param inpt: A file path or byte array to load data from
        :type inpt: str or bytes
        :param preprocessor: A function to call on the raw record data before
            enclosing it in the group object. The function should accept a list
            representing the output data as its first argument and a list
            representing the input data as its second argument.
        :type preprocessor: callable
        """
        if isinstance(inpt, str):
            input_data = pickle.load(inpt)
        elif isinstance(inpt, bytes):
            input_data = pickle.loads(inpt)
        else:
            raise TypeError(f"Data of invalid type: {type(inpt)}")
        
        group = ListRecordGroup()
        if preprocessor is not None:
            preprocessor(group._records, input_data)
        else:
            group._records = input_data
            
        return group
        
    def append(self, record):
        """
        :param record: Record to add to internal list
        """
        self._records.append(record)
        super().append(record)
        
    def shape(self):
        """
        :return: Number of records currently saved
        """
        return (len(self._records),)
        
class ArrayRecordGroup(RecordGroup):
    """
    A collection of numeric records stored in a numpy array.
    """
    
    def __init__(self, record_shape, max_records, dtype, record_axes=None):
        """
        :param record_shape: The shape of a single record
        :type record_shape: tuple
        :param max_records: The number of records to allocate memory for
        :type max_records: int
        :param dtype: Numeric type for record data
        :param record_axis: Axis values for a given record, to be stored with
            the record group's metadata. This should be a list of 1D arrays, 
            with each 1D array corresponding to a particular dimension of the
            record.
        """
        self._dtype = dtype
        self._records = None
        self._max_records = max_records
        self._count = 0
        self._record_shape = record_shape
        self._record_axes = record_axes if record_axes is not None else []
        
        super().__init__()
        
    @staticmethod
    def from_data(records):
        """
        Create an ArrayRecordGroup from a numpy array of data. It is implied
        that the first index iterates over individual records, and any other
        dimensions in the array are the dimensions of the individual records
        themselves.
        
        :param records: Data to ingest
        :type records: numpy array
        """
        inst = ArrayRecordGroup(records.shape[1:], records.shape[0], records.dtype)
        inst._records = records
        inst._count = records.shape[0]
        inst._record_axes = None
        return inst
        
    def serialize(self, output_file):
        axes = {f"axis{i}": ax for i,ax in enumerate(self._record_axes)} if self._record_axes is not None else {}                
        np.savez(output_file, 
                 allow_pickle=False, 
                 records=self._records[:self._count,...], 
                 **axes)
    
    @staticmethod  
    def load(inpt, preprocessor=None):
        """
        Load records from a file or bytes with an optional preprocessing stage.
        
        :param inpt: A file path or byte array to load data from
        :type inpt: str or bytes
        :param preprocessor: A function to call on the record data before
            enclosing it in the group object. The function should accept a 
            ``numpy.NpzFile`` object representing the input data and axes 
            as its only argument, and a dictionary should be returned with
            the key "records" containing the output data and the keys "axis<i>"
            containing the axes for the data in the records. Note that the 
            resulting record group will encapsulate these objects directly, 
            so any allocation or copying should be performed in the 
            preprocessing stage if necessary.
        :type preprocessor: callable
        """
        if isinstance(inpt, str):
            file = inpt
        elif isinstance(inpt, bytes):
            file = io.BytesIO(inpt)
        else:
            raise TypeError(f"Data of invalid type: {type(inpt)}")
        
        data = np.load(file, allow_pickle=False)
        group_data = preprocessor(data) if preprocessor is not None else data
        inst = ArrayRecordGroup.from_data(group_data["records"])
        if "axis0" in group_data:
            inst._record_axes = [group_data[f"axis{i}"] for i in range(group_data["records"].ndim-1)]
        
        return inst
        
    def __getitem__(self, k):
        """
        Retrieve a record specified by a key.
        """
        return np.take(self._records, k, axis=0)
    
    def append(self, record):
        """
        Add a record into the array.
        """
        if record.shape != self._record_shape:
            raise ValueError(f"Incompatible record shape (expected"
                             f" {self._record_shape}, received {record.shape})")
            
        if self._records is None:
            self._records = np.empty(shape=(self._max_records, 
                                            *self._record_shape), 
                                     dtype=self._dtype)
                        
        self._records[self._count, ...] = record    
        self._count += 1
        super().append(record)
        
    def shape(self):
        return (self._count, *(self._records.shape[1:]))
    
    def __len__(self):
        return self._count
    
    def axis(self, idx=0):
        """
        Get the axis for a given dimension.
        
        :param idx: Dimension to get axis for
        :type idx: int
        """
        return self._record_axes[idx]

class DataManager:
    """
    An abstraction for collecting and storing groups of data records.
    """
    
    def __init__(self, 
                 output_directory, 
                 subdirectory_prefix="", 
                 datetime_format="%m%d%y-%H%M%S",
                 save_count=20,
                 close_server=False):
        """
        Initializes a DataManager for collecting data records. Every time this
        is called, a subdirectory will be created within the specified output
        directory to store data for the particular measurement for which the
        instance was created. By default, the subdirectory name will be a 
        string representation of the time at which the DataManager was 
        created, and an optional prefix may be provided.
        
        Inside the directory, a metadata JSON file will be used for organizing
        data records and providing details about their contents.
        
        To prevent overloading disk I/O, one can specify how many new records 
        should be accepted before saving data. Data can be manually saved at
        any time by calling :meth:`save`.
        
        A TCP server will also be created; clients can connect to receive 
        announcements of new records. To prevent flooding the network with 
        data, announcements will be made only when data is saved.
        
        :param output_directory: Directory into which data will be written.
        :type output_directory: str
        :param subdirectory_prefix: Prefix for subdirectory name
        :type subdirectory_prefix: str
        :param datetime_format: Format string for the date and time in the 
            subdirectory name. Follows conventions for the ``datetime``
            module.
        :type datetime_format: str
        :param server_port: Port on which to create the server for announcing
            data updates
        :type server_port: int
        :param save_count: Specifies how many records should be received before
            saving data to disk and announcing it on the server
        :type save_count: int
        :param close_server: When using an instance as a context manager, this
            flag determines whether the server should be closed when exiting 
            the context. If this is `False`, exiting the context will block 
            until the server is manually closed by a client.
        :type close_server: bool
        """
        time_str = datetime.datetime.now(datetime.timezone.utc).strftime(datetime_format)
        self._output_directory = os.path.join(output_directory, f"{subdirectory_prefix}{time_str}")
        if not os.path.exists(self._output_directory):
            os.mkdir(self._output_directory)
            
        self._datetime_format = datetime_format
        self._saved_files = []
        self._groups = {}
        self._record_preprocessors = {}
        self._save_count = save_count
        self._record_count = 0
        self._server_thread = None
        self._progress_dict = {}
        self._progress_dict_lock = Lock()
        self._server_running_event = Event()
        self._server_stop_event = Event()
        self._record_lock = Lock()
        self._close_server = close_server
        
    @staticmethod
    def _server_thread(file_directory, address, record_lock, meta_container, meta_lock, running_event, stop_event, record_preprocessors):
        """
        A thread for providing access to files and data in the output 
        directory in a way that respects the requisite file locks.
        """
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        logging.debug(f"Started DataManager server at {address}")
        # Create the server
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.settimeout(0.1)
        s.bind(address)
        s.listen()
        
        running_event.set()
        
        # Continuously accept connections until the main thread commands otherwise
        while True:
            try:
                conn, addr = s.accept()
            except socket.timeout:
                if stop_event.is_set():
                    break
                else:
                    continue
                
            logging.debug(f"Received connection from {addr}")
            
            cmd = conn.recv(1)
            if cmd == b'g':
                # Receive a (potentially pre-processed) group
                # Get the length of the name of the group being requested
                group_name_length = int.from_bytes(conn.recv(1), "little")
                logging.debug(f"Group name length {group_name_length}")
                
                # Get the group name
                group_name_bytes = b''
                while len(group_name_bytes) < group_name_length:
                    group_name_bytes += conn.recv(group_name_length - len(group_name_bytes))
                group_name = group_name_bytes.decode("ascii")
                logging.debug(f"Requested group {group_name}")
                
                # Load the metadata to get the group type and filename
                with record_lock:
                    if "metadata.json" not in os.listdir(file_directory):
                        # No data yet
                        conn.sendall((0).to_bytes(1, "little"))
                        conn.close()
                        continue
                        
                    with open(os.path.join(file_directory, "metadata.json"), "rb") as f:
                        metadata = json.load(f)
                    
                    group_type = metadata['groups'][group_name]['type']
                    group_filename = os.path.join(file_directory, metadata['groups'][group_name]['filename'])
                    logging.debug(f"Identified group as type {group_type}")
                    
                    conn.sendall(len(group_type).to_bytes(1, "little"))
                    conn.sendall(group_type.encode('ascii'))
                    logging.debug(f"Sent group type {group_type}")

                    if group_name in record_preprocessors:
                        # If the data is to be preprocessed, create a new group and
                        # send the serialized version of that
                        group = eval(group_type).load(group_filename, record_preprocessors[group_name])
                        data = io.BytesIO()
                        group.serialize(data)
                        data_size = data.tell()
                        data.seek(0)
                        
                    else:
                        # If there's no preprocessing to do, just send the data file
                        data_size = os.path.getsize(group_filename)
                        data = open(group_filename, "rb")
                            
                    conn.sendall(data_size.to_bytes(8, "little"))
                    logging.debug(f"Sent data size {data_size}")
                    
                    conn.sendfile(data)
                    logging.debug(f"Sent file")
                    
                    data.close()
            elif cmd == b'p':
                # Return the internal meta container
                logging.debug("Progress command")
                with meta_lock:
                    logging.debug(f"Progress: {meta_container}")
                    data = pickle.dumps(meta_container)
                    conn.sendall(len(data).to_bytes(8, "little"))
                    conn.sendall(data)
            elif cmd == b'q':
                logging.debug("Closing server from manual command")
                break
                    
            else:
                logging.error(f"Received invalid command {cmd}")
                
            # Close the connection and accept a new one
            conn.close()
            
        s.close()
        running_event.clear()
    
    @staticmethod
    def receive_group(group_name, address):
        """
        Receive a data group from a server.
        """
        
        logging.debug(f"Requesting group {group_name} from {address}")
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            s.connect(address)
        except:
            logging.debug("Failed to connect")
            return None
        
        logging.debug(f"Established connection to server {address}")
        
        s.sendall(b'g')
        logging.debug("Sent group command")
        
        s.sendall(len(group_name).to_bytes(1, "little"))
        logging.debug(f"Sent group name length {len(group_name)}")
        
        s.sendall(group_name.encode("ascii"))
        logging.debug(f"Sent group name {group_name}")
        
        group_type_length_bytes = s.recv(1)
        group_type_length = int.from_bytes(group_type_length_bytes, "little")
        logging.debug(f"Received group type length {group_type_length}")
        
        if group_type_length == 0:
            return None
        
        group_type_bytes = b''
        while len(group_type_bytes) < group_type_length:
            group_type_bytes += s.recv(group_type_length - len(group_type_bytes))
        group_type = group_type_bytes.decode('ascii')
        logging.debug(f"Received group type {group_type}")
        
        data_length_bytes = b''
        while len(data_length_bytes) < 8:
            data_length_bytes += s.recv(8 - len(data_length_bytes))
            
        data_length = int.from_bytes(data_length_bytes, "little")
        logging.debug(f"Server responded with data size {data_length}")
        
        if data_length == 0:
            return None
        
        data = b''
        while len(data) < data_length:
            data += s.recv(data_length - len(data))
            
        logging.debug(f"Received data")
        
        return eval(group_type).load(data)
    
    @staticmethod
    def receive_counters(address):
        """
        Receive the progress counters from a server at the specified address.
        
        :return: Progress counters if the server has one, otherwise `None`
        :rtype: dict
        """        
        logging.debug(f"Requesting progress from {address}")
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            s.connect(address)
        except:
            logging.debug("Failed to connect")
            return None
        
        logging.debug(f"Established connection to server {address}")
        
        s.sendall(b'p')
        logging.debug("Sent progress command")
        
        data_length_bytes = b''
        while len(data_length_bytes) < 8:
            data_length_bytes += s.recv(8-len(data_length_bytes))
        data_length = int.from_bytes(data_length_bytes, "little")
        
        data = b''
        while len(data) < data_length:
            data += s.recv(data_length - len(data))
        
        counters = pickle.loads(data)
        logging.debug(f"Received {counters}")
        
        return counters
    
    @staticmethod
    def stop_remote_server(address):
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            s.connect(address)
        except:
            logging.debug("Failed to connect")
            return None
        
        logging.info(f"Established connection to server {address}")
        
        s.sendall(b'q')
        s.close()
        
    def start_server(self, address=("", 6672)):
        """
        Launch a server process that will allow other processes or machines to
        receive files or record groups from this DataManager.
        
        :param address: Address for hosting the server
        :type address: tuple (for network sockets) or str (for Unix sockets)
        """
        self._server_thread = Thread(target=DataManager._server_thread, 
                   args=(self._output_directory, 
                         address, 
                         self._record_lock, 
                         self._progress_dict,
                         self._progress_dict_lock,
                         self._server_running_event,
                         self._server_stop_event,
                         self._record_preprocessors),
                   name=f"DataManager@{address}",
                   daemon=True)
        self._server_thread.start()
        
    def stop_server(self):
        """
        Stop the server and all associated threads.
        """
        self._server_stop_event.set()
        self._server_thread.join()
        self._server_stop_event.clear()
        self._server_threads = []
        
    def server_running(self):
        """
        Check whether or not the server is running.
        
        :rtype: bool
        """
        return self._server_running_event.is_set()
        
    def append(self, group_name, record):
        self._groups[group_name].append(record)
        self._record_count += 1        
        if self._record_count == self._save_count:
            self.save()
        
    def save(self):
        """
        Commit data in all groups to files.
        """
                
        with self._record_lock:
            logging.debug("Saving records...")
            with open(os.path.join(self._output_directory, "metadata.json"), "w+") as file:
                metadata = {"datetime_format": self._datetime_format, 
                            "groups": {}, 
                            "files": []}
                for name,group in self._groups.items():
                    group_metadata = {
                        "type": group.__class__.__name__,
                        "length": len(group),
                        "filename": name,
                        "metadata": group.metadata()
                    }
                    
                    metadata["groups"][name] = group_metadata
                    
                    with open(os.path.join(self._output_directory, name), "wb+") as f:
                        group.serialize(f)
                        
                for saved_file in self._saved_files:
                    metadata["files"].append(saved_file)
                        
                json.dump(metadata, file)
            
            logging.debug("Saved")
        
        # Clear the record count so that we wait the right amount of time
        # before saving again
        self._record_count = 0
                        
    def save_file(self, file, suffix=""):
        """
        Copy a file into the output directory for this DataManager. An optional
        file suffix may be added so that the same file can be copied multiple 
        times, if desired.
        
        :param file: Absolute path to the file
        :type file: str
        :return: The path to the copied file
        :rtype: str
        """
        
        logging.debug(f"Saving file {file}")
        
        dst = os.path.join(self._output_directory, f"{os.path.basename(file)}{suffix}")
        filename = shutil.copy2(file, dst)
        
        self._saved_files.append({
            "src": file, 
            "dst": filename, 
            "time": datetime.datetime.now(datetime.timezone.utc).strftime(self._datetime_format)
        })
        
    def add_group(self, name, group, preprocessor=None):
        """
        Add a group to be managed with an optional remote preprocessor.
        
        :param name: Name of group
        :type name: str
        :param group: Group to be managed
        :type group: :class:`RecordGroup`
        :param preprocessor: A preprocessing function for the record data. 
            Note that any preprocessing only applies to data sent by the 
            server, NOT to data written to disk. For descriptions of the 
            preprocessor requirements, see the documentation of :meth:`load`
            for the corresponding `RecordGroup` subclass. 
        """
        if name in self._groups:
            raise KeyError(f"Group {name} already exists.")
        
        if not isinstance(group, RecordGroup):
            raise TypeError("Only `RecordGroup` instances can be added")
        
        self._groups[name] = group
        
        if preprocessor is not None:
            self._record_preprocessors[name] = preprocessor
            
    def progress_advance(self):
        """
        Notify the internal progress counter to increment by 1.
        """
        with self._progress_dict_lock:
            self._progress_dict["progress"] += 1
            
    def progress_complete(self):
        """
        Notify the internal progress counter that data collection is complete.
        """
        with self._progress_dict_lock:
            self._progress_dict["complete"] = True
            
    def iterator_progress(self, it):
        """
        Use an iterable to track progress through a program. If this method is
        called, an internal counter is stored which may be retrieved with the 
        server.
        
        :param it: Iterator to consume
        :type it: iterator
        :return: A generator that yields the provided iterator's return values
            while simultaneously updating the internal progress counter.
        """
        with self._progress_dict_lock:
            self._progress_dict["total"] = len(it) if hasattr(it, "__len__") else None
            self._progress_dict["progress"] = 0
            self._progress_dict["complete"] = False
                
        for item in it:
            yield item
            self.progress_advance()
                
        self.progress_complete()
                