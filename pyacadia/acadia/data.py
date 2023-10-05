import os
import datetime
import shutil
import json
import fcntl
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
    def load(inpt):
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
    def load(inpt):
        """
        Load records from a file or bytes.
        """
        if isinstance(inpt, str):
            return ListRecordGroup(pickle.load(inpt))
            
        if isinstance(inpt, bytes):
            return ListRecordGroup(pickle.loads(inpt))
        
        raise TypeError(f"Data of invalid type: {type(inpt)}")
        
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
        return inst
        
    def serialize(self, output_file):
        axes = {f"axis{i}": ax for i,ax in enumerate(self._record_axes)}                
        np.savez(output_file, 
                 allow_pickle=False, 
                 records=self._records[:self._count,...], 
                 **axes)
    
    @staticmethod  
    def load(inpt):
        if isinstance(inpt, str):
            file = inpt
        elif isinstance(inpt, bytes):
            file = io.BytesIO(inpt)
        else:
            raise TypeError(f"Data of invalid type: {type(inpt)}")
        
        data = np.load(file, allow_pickle=False)
        
        inst = ArrayRecordGroup.from_data(data["records"])
        inst._record_axes = [data[f"axis{i}"] for i in range(data["records"].ndim-1)] if "axis0" in data else None
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
                 save_count=20):
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
        """
        time_str = datetime.datetime.now(datetime.timezone.utc).strftime(datetime_format)
        self._output_directory = os.path.join(output_directory, f"{subdirectory_prefix}{time_str}")
        if not os.path.exists(self._output_directory):
            os.mkdir(self._output_directory)
            
        self._datetime_format = datetime_format
        self._saved_files = []
        self._groups = {}
        
        self._save_count = save_count
        self._record_count = 0
        self._server_threads = []
        
        self._server_stop_event = Event()
        
        self._lock = Lock()
        
    @staticmethod
    def _server_thread(file_directory, address, lock, stop_event):
        """
        A thread for providing access to files in the output directory in a 
        way that respects the requisite file locks.
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
        
        # Continuously accept connections that will request files
        while True:
            try:
                conn, addr = s.accept()
            except socket.timeout:
                if stop_event.is_set():
                    s.close()
                    break
                else:
                    continue
                
            logging.debug(f"Received connection from {addr}")
            
            # Get the length of the name of the file being requested
            filename_length = int.from_bytes(conn.recv(1), "little")
            logging.debug(f"Filename length {filename_length}")
            
            # Get the filename
            filename_bytes = b''
            while len(filename_bytes) < filename_length:
                filename_bytes += conn.recv(filename_length - len(filename_bytes))
            filename = filename_bytes.decode("ascii")
            logging.debug(f"Requested file {filename}")
                
            # send an 8-byte file length
            if filename not in os.listdir(file_directory):
                logging.debug(f"File not found")
                conn.sendall((0).to_bytes(8, "little"))
            else:
                with lock:
                    logging.debug(f"Data lock acquired")
                    file_size = os.path.getsize(os.path.join(file_directory, 
                                                            filename))
                    conn.sendall(file_size.to_bytes(8, "little"))
                    logging.debug(f"Located file, sent size {file_size}")
                    
                    # Send the file
                    with open(os.path.join(file_directory, filename), "rb") as file:
                        conn.sendfile(file)
                        
                    logging.debug(f"File {filename} sent")
                
            # Close the connection and accept a new one
            conn.close()
            
    @staticmethod
    def receive_file(filename, address):
        """
        Receive a file from a server.
        """
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.connect(address)
        logging.debug(f"Established connection to server {address}")
        
        s.sendall(len(filename).to_bytes(1, "little"))
        logging.debug(f"Sent filename length {len(filename)}")
        
        s.sendall(filename.encode("ascii"))
        logging.debug(f"Sent filename {filename}")
        
        file_length_bytes = b''
        while len(file_length_bytes) < 8:
            file_length_bytes += s.recv(8 - len(file_length_bytes))
            
        file_length = int.from_bytes(file_length_bytes, "little")
        logging.debug(f"Server responded with file size {file_length}")
        
        if file_length == 0:
            return None
        
        file_data = b''
        while len(file_data) < file_length:
            file_data += s.recv(file_length - len(file_data))
            
        logging.debug(f"Received file")
            
        return file_data
    
    @staticmethod
    def receive_group(group_name, address):
        """
        Receive a data group from a server.
        """
        logging.debug(f"Requesting group {group_name} from {address}")
        metadata_bytes = DataManager.receive_file("metadata.json", address)
        if metadata_bytes is None:
            logging.debug(f"Received no metadata")
            return None
        
        metadata = json.loads(metadata_bytes)
        group_type = metadata['groups'][group_name]['type']
        logging.debug(f"Received metadata, group is of type {group_type}")
        
        group_data = DataManager.receive_file(metadata["groups"][group_name]["filename"], address)
        logging.debug(f"Received records from server")
        
        if group_data is None:
            logging.debug("Received no group data")
            return None
        
        group = eval(group_type).load(group_data)
        logging.debug(f"Group contains {len(group)} records")
        
        return group
        
    def start_server(self, address=("", 6672)):
        """
        Launch a server process that will allow other processes or machines to
        receive files or record groups from this DataManager.
        
        :param address: Address for hosting the server
        :type address: tuple (for network sockets) or str (for Unix sockets)
        """
        t = Thread(target=DataManager._server_thread, 
                   args=(self._output_directory, 
                         address, 
                         self._lock, 
                         self._server_stop_event),
                   name=f"DataManager@{address}",
                   daemon=True)
        t.start()
        self._server_threads.append(t)
        
    def stop_server(self):
        """
        Stop the server and all associated threads.
        """
        self._server_stop_event.set()
        for t in self._server_threads:
            t.join()
        self._server_stop_event.clear()
        self._server_threads = []
        
    def append(self, group_name, record):
        self._groups[group_name].append(record)
        self._record_count += 1        
        if self._record_count == self._save_count:
            self.save()
        
    def save(self):
        """
        Commit data in all groups to files.
        """
                
        with self._lock:
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
        
    @staticmethod
    def load_group(directory, group_name):
        """
        Load a group of records from a data file in a given directory. The
        type of the returned group will match that of the stored group.
        
        :param directory: Data directory from which to load group data
        :type directory: str
        :param group_name: Name of the group to load
        :type group_name: str
        :return: A record group containing the loaded data
        :rtype: A subclass of :class:`RecordGroup`
        """
        logging.debug(f"Loading records in group {group_name} from {directory}")
        
        file = open(os.path.join(directory, "metadata.json"), "w+")
        
        metadata = json.load(file)
            
        if group_name not in metadata["groups"]:
            file.close()
            raise ValueError(f"Unable to find group {group_name}")
        
        group = metadata["groups"][group_name]
        
        with open(group["filename"], "rb") as f:
            group_obj = eval(group["type"]).load(f)
            
        file.close()
        
        logging.debug(f"Loaded {len(group_obj)} records")
        
        return group_obj
                        
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
        
    def add_group(self, name, group):
        """
        Add a group to be managed.
        
        :param name: Name of group
        :type name: str
        :param group: Group to be managed
        :type group: :class:`RecordGroup`
        """
        if name in self._groups:
            raise KeyError(f"Group {name} already exists.")
        
        if not isinstance(group, RecordGroup):
            raise TypeError("Only `RecordGroup` instances can be added")
        
        self._groups[name] = group
        
class Plotter:
    """
    A class for requesting data from :class:`DataManager` instances and 
    creating live plots with processing pipelines. The 
    """
    
    def __init__(self, plot_generator):
        """
        :param plot_generator: An iterable function for drawing the plot. The
            function is expected to yield the created figure after updating the
            data in any plotted objects. The function must accept a single dict
            as an argument whose keys will be group names and whose values are
            :class:`RecordGroup` instances containing their data.
        :type plot_generator: callable
        """
        self._plot_generator = plot_generator
        self._thread = None
        self._thread_stop = Event()
        
    @staticmethod
    def _plot_thread(update_period, server_address, plot_generator, thread_stop_event):
        import time
        import matplotlib.pyplot as plt
        import numpy as np
        
        logging.debug(f"Plotter thread launched to retrieve records from {server_address}")
        
        groups = {}
        
        # Create the generator for updating plots
        gen = plot_generator(groups)
        
        while True:
            if thread_stop_event.is_set():
                logging.debug("Received stop event")
                break
            # Wait a bit so that we have some new data
            time.sleep(update_period)
            
            # Get metadata so that we know what groups we have
            metadata_bytes = DataManager.receive_file("metadata.json", 
                                                       server_address)
            if metadata_bytes is None:
                logging.debug("Received no metadata")
                continue
                
            metadata = json.loads(metadata_bytes)
            
            logging.debug(f"Received metadata with {len(metadata['groups'])} groups")
            
            # Get the groups themselves
            for group_name,group_metadata in metadata["groups"].items():
                group = DataManager.receive_group(group_name, server_address)
                groups[group_name] = group

            # Update plots using the provided generator
            fig = next(gen)
            
            # # Redraw
            # fig.canvas.draw() 

    def run(self, server_address=("localhost", 6672), update_period=0.2):
        """
        Periodically poll the server for data and update all plots.
        
        :param update_period: The amount of time to wait before polling a 
            server for data updates
        :type update_period: float
        """        
        self.stop()
        self._thread = Thread(target=Plotter._plot_thread, 
                              args=(update_period, 
                                    server_address, 
                                    self._plot_generator,
                                    self._thread_stop),
                              name=f"Plotter@{server_address}",
                              daemon=True)
        self._thread.start()
        
    def stop(self):
        """
        Stop any running plot threads
        """
        if self._thread is not None:
            self._thread_stop.set()
            self._thread.join()
            self._thread_stop.clear()
            self._thread = None