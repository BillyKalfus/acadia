import os
import datetime
import shutil
import json
import pickle
import numpy as np
import io
import logging
import socket
import fcntl
import subprocess
import traceback
import time
import struct
import operator
from functools import reduce
from itertools import count
from abc import ABC, abstractstaticmethod, abstractmethod
from numpy.lib.format import header_data_from_array_1_0, descr_to_dtype

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
    def serialize(self, record_indices=None, out=None):
        """
        Convert the record group and all of its data (or a user-provided 
        subset) into a stream of bytes. The output will be fully rewritten
        every time this is called, so :meth:`save` should be used for 
        frequent, fast updates.
        
        :param record_indices: Indices of records to serialize. If `None`, all
            records are included.
        :type record_indices: array-like or None
        :param out: If not `None`, this can be either a `str` or file-like 
            object. If a `str`, this argument is treated as a filepath into
            which the serialized data should be written. If a file-like object,
            the object's `write` method will be used to write the data. If 
            `None`, the serialized data is returned as a newly-allocated 
            ``io.BytesIO`` object.
        :type out: str, file-like object, or None
        """
        pass
    
    @abstractstaticmethod
    def deserialize(input_data):
        """
        The inverse of :meth:`serialize`; create a new instance from a stream 
        of serial data.
        
        :param input_data: this can be either a `str` or file-like 
            object. If a `str`, this argument is treated as a filepath from
            which the serialized data should be read. If a file-like object,
            the object's `read` method will be used to read the data.
        :type input_data: str or file-like object
        """
        pass
    
    @abstractmethod
    def save(self, group_name, output_dir):
        """
        Save the data in the record group into files. This should be used 
        instead of :meth:`serialize` when frequent, fast updates to the file
        storage are desired.
        
        :param group_name: Group name
        :type group_name: str
        :param output_dir: Directory into which group files will be saved
        :type output_dir: str
        """
        pass
    
    @abstractstaticmethod
    def load(group_name, input_dir, metadata=None, map=True):
        """
        Load data from files into a new instance.
        
        :param group_name: Group name
        :type group_name: str
        :param input_dir: Directory from which group files will be loaded
        :type input_dir: str
        :param metadata: Some types will require additional data for loading,
            such as array types or shapes. This is subclass-specific and is
            not required to be accessed.
        :type metadata: dict
        :param map: Indicate that memory-mapped data is preferred, if the 
            class supports it.
        :type map: bool
        """
        pass
    
    @abstractmethod    
    def records(self):
        """
        :return: The underlying record data, whose type will be specific to the
            instance class.
        """
        pass
    
    @abstractmethod
    def append(self, record) -> None:
        """
        Append a new record to internal storage. Note that this does not save 
        the data in any way, and recoverable storage should be created by 
        calling :meth:`save` or :meth:`serialize`.
        
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
    
    @abstractmethod
    def __len__(self) -> int:
        """
        :return: The number of records stored in the group
        :rtype: int
        """
        pass
    
    @abstractmethod
    def __getitem__(self, k):
        """
        :return: The internally-stored record specified by key `k`
        """
        pass
        
class ArrayRecordGroup(RecordGroup):
    """
    A collection of similarly-shaped array-like records.
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
        self._last_saved_args = None
        self._metadata = {}
        
        super().__init__()
    
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
    
    def _save_array(self, arr, output_dir, filename):
        with open(os.path.join(output_dir, filename), "wb") as f:
            arr.tofile(f)
                        
        self._metadata[filename] = header_data_from_array_1_0(arr)
        
    def save(self, group_name, output_dir):
        """
        Save the data in the record group into files. A file will be created
        for the primary data, and additional files will be created for the 
        axes.
        """
        
        # If our most recent call to this function had the same arguments,
        # append to files instead of rewriting everything
        # Additionally, the axes will only be written the first time        
        if self._last_saved_args is None or self._last_saved_args["dir"] != output_dir or self._last_saved_args["name"] != group_name:
            # First-time write, save the axes and update internal metadata
            for i,axis in enumerate(self._record_axes):
                self._save_array(axis, output_dir, f"{group_name}_axis{i}.bin")
                    
            # We have to save from the beginning of the file
            record_offset = 0
        else:
            # We've saved here before, we can append from where we left off
            # and we don't need to save the axes again
            record_offset = self._last_saved_args["count"]
            
        if record_offset != self._count:
            self._save_array(self._records[:self._count, ...], output_dir, f"{group_name}_records.bin")
            self._last_saved_args = {"dir": output_dir, 
                                    "name": group_name, 
                                    "count": self._count}
            
    @staticmethod
    def _load_array(filename, input_dir, header_data, map=False):
        full_path = os.path.join(input_dir, filename)
        
        logging.debug(f"{'Mapping' if map else 'Loading'} {full_path} with header {header_data}")
        
        if not os.path.isfile(full_path):
            logging.debug(f"Unable to find array data for {filename} in"
                          f" directory {input_dir}")
            return None
        
        if filename not in header_data:
            logging.debug(f"No header for {filename} found")
            return None
        
        dtype = descr_to_dtype(header_data[filename]["descr"])
        order = 'F' if header_data[filename]["fortran_order"] else 'C'
        shape = tuple(header_data[filename]["shape"])
        
        logging.debug(f"Extracted: dtype {dtype}, order {order}, shape {shape}")
        
        if map:
            arr = np.memmap(full_path, dtype=dtype, mode="r", shape=shape, order=order)
        else:
            arr = np.fromfile(full_path, dtype=dtype, count=reduce(operator.mul, shape))
            arr = np.reshape(arr, shape, order=order)
            
        return arr
    
    @staticmethod  
    def load(group_name, input_dir, metadata=None, map=False):
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
        
        records = ArrayRecordGroup._load_array(f"{group_name}_records.bin", input_dir, metadata, map)
        if records is None:
            return None
        
        record_axes = []
        for axis_idx in count():
            axis_filename = f"{group_name}_axis{axis_idx}.bin"
            if os.path.exists(os.path.join(input_dir, axis_filename)):
                axis = ArrayRecordGroup._load_array(axis_filename, input_dir, metadata, map)
                record_axes.append(axis)
            else:
                break
            
        # Create a record group from the data we loaded
        inst = ArrayRecordGroup(records.shape[1:], records.shape[0], records.dtype, record_axes)
        inst._records = records
        inst._count = inst._max_records
        
        return inst
    
    def serialize(self, record_indices=None, out=None):
        if out is None:
            out = io.BytesIO()
            created_out = True
        else:
            created_out = False
            
        records = np.take(self._records[:self._count,...], record_indices, axis=0)
        axes = {f"axis{i}": ax for i,ax in enumerate(self._record_axes)}               
        np.savez(out, allow_pickle=False, records=records, **axes)
        
        if created_out:
            return out
        
    @staticmethod
    def deserialize(input_data):
        data = np.load(input_data)
        
        record_axes = []
        for i in count():
            if f"axis{i}" in data:
                record_axes.append(data[f"axis{i}"])
        
        inst = ArrayRecordGroup(data["records"].shape[1:], 
                                data["records"].shape[0], 
                                data["records"].dtype, 
                                record_axes)
        
        inst._records = data["records"]
        inst._count = inst._max_records
        
        return inst
            
    def __getitem__(self, k):
        return np.take(self._records, k, axis=0)
    
    def append(self, record):
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
    
    def __len__(self):
        return self._count
    
    def records(self):
        return self._records
    
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
        
    @staticmethod
    def _sendint(sock, i: int):
        """
        Send an integer over a socket.
        """
        sock.sendall(i.to_bytes(8, "little"))
        
    @staticmethod
    def _recvint(sock):
        """
        Receive an integer from a socket.
        """
        tstart = time.time()
        i_bytes = b''
        while len(i_bytes) < 8:
            if time.time() - tstart > 1:
                raise TimeoutError(f"Failed to receive int (received {len(i_bytes)} bytes)")
            i_bytes += sock.recv(8 - len(i_bytes))
        return int.from_bytes(i_bytes, "little")
        
    @staticmethod
    def _sendstring(sock, s):
        """
        Send an ASCII string over a socket.
        """
        s_ascii = s.encode("ascii")
        DataManager._sendint(sock, len(s_ascii))
        sock.sendall(s_ascii)
        
    @staticmethod
    def _recvstring(sock):
        """
        Receive an ASCII string from a socket
        """
        s_length = DataManager._recvint(sock)
        logging.debug(f"Received string length {s_length}")
        
        if s_length == 0:
            return ""
        
        buf = io.BytesIO()
        tstart = time.time()
        while buf.tell() < s_length:
            if time.time() - tstart > 1:
                raise TimeoutError(f"Failed to receive str (received {buf.tell()} bytes)")
            buf.write(sock.recv(s_length - buf.tell()))
            
            
        buf.seek(0)
        return buf.read().decode("ascii")
        
    @staticmethod
    def _sendfile(sock: socket.socket,
                    filename: str, 
                    directory: str, 
                    lock: bool = True, 
                    file_data_preprocessor=None):
        """
        Send a file over a socket.
        
        :param filename: Basename of the file
        :type filename: str
        :param directory: Directory containing the file
        :type directory: str
        :param s: Socket over which to send file
        :type s: socket.socket
        :param lock: If `True`, an exclusive advisory lock is acquired for the
            file before reading
        :type lock: bool
        :param file_data_preprocessor: When the file data is read, it may be 
            optionally pre-processed by a function that will accept the file
            object and return the bytes to send.
        """
        file_path = os.path.join(directory, filename)
        if not os.path.exists(file_path):
            logging.error(f"File {filename} not found in directory {directory}")
            return
        
        DataManager._sendstring(sock, filename)
        
        # Send file size and file
        file_size = os.path.getsize(file_path)
        
        with open(file_path, "rb") as f:
            if lock:
                fcntl.fcntl(f, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_RDLCK, 0, 0, 0, 0, 0))
            if file_data_preprocessor is not None:
                preprocessed_data = file_data_preprocessor(f)
                data_size = len(preprocessed_data)
                DataManager._sendint(sock, data_size)
                sock.sendall(preprocessed_data)
            else:
                data_size = file_size
                DataManager._sendint(sock, file_size)
                sock.sendfile(f, count=file_size)
            if lock:
                fcntl.fcntl(f, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0))
        
        logging.debug(f"Sent file {filename} ({file_size} bytes, sent {data_size})") 
        
    @staticmethod
    def _recvfile(sock: socket.socket, output_directory, timeout=1):
        """
        Receive a file from a socket. The file will be written with a filename
        provided by the socket, and the filename and size will be returned.
        """  
        
        filename = DataManager._recvstring(sock)
        file_size = DataManager._recvint(sock)
        
        logging.debug(f"Receiving file {filename} ({file_size} bytes)")
        
        with open(os.path.join(output_directory, filename), "wb") as f:
            tstart = time.time()
            while f.tell() < file_size:
                if time.time() - tstart > timeout:
                    raise TimeoutError(f"Timed out receiving file {filename}"
                                       f" (received {f.tell()}/{file_size} bytes)")
                piece = sock.recv(file_size - f.tell())
                logging.debug(f"Received {len(piece)}-byte chunk")
                f.write(piece)
                
        logging.debug(f"Received file {filename}")
        
                        
    @staticmethod
    def _server_process_func(file_directory, address):
        """
        A thread for providing access to files and data in the output 
        directory in a way that respects the requisite file locks.
        """
        logging.debug("Server process launched")
        
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        # Create the server
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.settimeout(0.2)
        s.bind(address)
        s.listen()
        
        logging.debug(f"Started DataManager server at {address}")
        
        stop_file_path = os.path.join(file_directory, ".stop")
        
        # Continuously accept connections until the main thread commands otherwise
        while True:
            try:
                conn, addr = s.accept()
                logging.debug(f"Received connection from {addr}")
                conn.settimeout(1)
            except socket.timeout:
                if os.path.exists(stop_file_path):
                    logging.info("Stop file located, stopping")
                    os.remove(stop_file_path)
                    break
                else:
                    continue
                
            try:
                cmd_id = DataManager._recvint(conn)
                cmd = DataManager._recvint(conn)
                logging.debug(f"(id {cmd_id}) Received command {cmd}")
                
                if cmd == 1:
                    # Receive group metadata and files
                    # Get the length of the name of the group being requested
                    group_name = DataManager._recvstring(conn)
                    logging.debug(f"(id {cmd_id}) Requested group {group_name}")
                    
                    # Load the metadata to get the group type and filename
                    if not os.path.exists(os.path.join(file_directory, "metadata.json")):
                        # No data yet
                        logging.error(f"(id {cmd_id}) File metadata.json not found in directory {file_directory}")
                        DataManager._sendstring(conn, "{}")
                    else:
                        with open(os.path.join(file_directory, "metadata.json"), "ab+") as f:
                            fcntl.fcntl(f, fcntl.F_SETLKW, struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0))
                            logging.debug(f"(id {cmd_id}) Locked metadata")
                            
                            f.seek(0)
                            group_metadata = json.load(f)['groups'][group_name]
                            
                            fcntl.fcntl(f, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0))
                            logging.debug(f"(id {cmd_id}) Released metadata")
                                        
                        data = json.dumps(group_metadata)
                        logging.debug(f"(id {cmd_id}) Sending metadata {data}")
                        DataManager._sendstring(conn, data)

                        # The metadata will contain all the names of the files to be sent 
                        for idx,file in enumerate(group_metadata["files"]):
                            file_path = os.path.join(file_directory, file)
                            if not os.path.exists(file_path):
                                logging.debug(f"(id {cmd_id}) File in metadata not found: {file}")
                            else:
                                logging.debug(f"(id {cmd_id}) Sending {file} ({os.path.getsize(file_path)} bytes)")  
                                DataManager._sendfile(conn, file, file_directory, lock=False)
                                # proc = subprocess.run(f"cat {file_path} | nc -c -l -p {address[1]+idx+1}", shell=True)
                                logging.debug(f"(id {cmd_id}) Sent")             
                    
                elif cmd == 2:
                    logging.debug(f"(id {cmd_id}) Progress command")
                    if not os.path.exists(os.path.join(file_directory, "progress.json")):
                        logging.debug(f"(id {cmd_id}) Progress file not found")
                        DataManager._sendstring(conn, "{}")
                    else:                    
                        with open(os.path.join(file_directory, "progress.json"), "a+") as f:
                            fcntl.fcntl(f, fcntl.F_SETLKW, struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0))
                            logging.debug(f"(id {cmd_id}) Locked progress")
                            
                            f.seek(0)
                            data = f.read()
                            logging.debug(f"(id {cmd_id}) Sending progress {data}")
                            DataManager._sendstring(conn, data)
                            
                            fcntl.fcntl(f, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0))
                            logging.debug(f"(id {cmd_id}) Released progress")
                
                elif cmd == 3:
                    logging.debug(f"(id {cmd_id}) Closing server from manual command")
                    with open(stop_file_path, "w+") as f:
                        f.write("stop from client")
                        
                else:
                    logging.error(f"(id {cmd_id}) Received invalid command {cmd}")
                    
                # Close the connection and accept a new one
                conn.close()
            except:
                logging.debug(f"Exception in server loop: {traceback.format_exc()}")
                
        s.close()
        
    @staticmethod
    def _create_server_connection(address):
        """
        Connect to a server and return a socket with the active connection.
        """
        if isinstance(address, tuple):
            socket_family = socket.AF_INET
        elif isinstance(address, str):
            socket_family = socket.AF_UNIX
        else:
            raise TypeError(f"Received address of invalid type: {address}")
        
        s = socket.socket(socket_family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.settimeout(2)
        
        try:
            s.connect(address)
        except:
            logging.debug(f"Failed to connect: {traceback.format_exc()}")
            return None

        logging.debug(f"Established connection to server {address}")
        
        return s
    
    @staticmethod
    def receive_group(group_name, address, temp_directory="/tmp"):
        """
        Receive a data group from a server.
        """
        id = np.random.randint(1e6)
        
        logging.debug(f"(cmd id {id}) Requesting group {group_name}")
        sock = DataManager._create_server_connection(address)
        
        if sock is None:
            logging.debug("Failed to connect to server.")
            return None
        # sock.settimeout(0.5)
        
        DataManager._sendint(sock, id)
        DataManager._sendint(sock, 1) 
        
        DataManager._sendstring(sock, group_name)
        metadata_str = DataManager._recvstring(sock)
        
        if len(metadata_str) == 0 or metadata_str == "{}":
            return None
        
        metadata = json.loads(metadata_str)
        
        logging.debug(f"(id {id}) Received metadata {metadata}")
        
        if len(metadata["files"]) == 0:
            # The metadata contains some record of files that will be written
            # but aren't ready yet
            logging.error(f"(id {id}) No files in metadata")
            sock.close()
            return None
        
        for idx,file in enumerate(metadata["files"]):
            file_path = os.path.join(temp_directory, file)
            logging.debug(f"(id {id}) Receiving file {file}")
            # done = False
            # tstart = time.time()
            # while not done:
            #     if time.time() - tstart > 1:
            #         logging.error(f"(id {id}) Failed to receive file {file}")
            #         sock.close()
            #         return None
                
            #     proc = subprocess.run(f"nc 192.168.2.69 {address[1]+idx+1} > {file_path}", shell=True)
            #     done = proc.returncode == 0
            
            DataManager._recvfile(sock, temp_directory)
            logging.debug(f"(id {id}) Received file {file} ({os.path.getsize(file_path)} bytes)")
            
        sock.close()
        
        group_type = eval(metadata["type"])
        
        return group_type.load(group_name, temp_directory, metadata=metadata["metadata"])
    
    @staticmethod
    def receive_counters(address):
        """
        Receive the progress counters from a server at the specified address.
        
        :return: Progress counters if the server has one, otherwise `None`
        :rtype: dict
        """        
        id = np.random.randint(1e6)
        logging.debug(f"(id {id}) Requesting progress")
        sock = DataManager._create_server_connection(address)   
        if sock is None:
            logging.debug(f"(id {id}) Failed to connect to server.")
            return None
          
        DataManager._sendint(sock, id)
        DataManager._sendint(sock, 2) 
        
        # logging.debug("Send progress command")
        data = DataManager._recvstring(sock)
        # logging.debug(f"Received {data}")
        sock.close()
        
        return json.loads(data)
    
    @staticmethod
    def stop_remote_server(address):
        sock = DataManager._create_server_connection(address)   
        id = np.random.randint(1e6)
        logging.debug(f"(id {id}) Requesting remote server exit")
        
        DataManager._sendint(sock, id)
        DataManager._sendint(sock, 3) 
        sock.close()
        
    def __init__(self, 
                 output_directory, 
                 subdirectory_prefix="", 
                 datetime_format="%m%d%y-%H%M%S",
                 save_count=5):
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
        self._server_process = None
        self._progress_dict = {}
        
    def start_server(self, address=("", 6672)):
        """
        Launch a server process that will allow other processes or machines to
        receive files or record groups from this DataManager.
        
        :param address: Address for hosting the server
        :type address: tuple (for network sockets) or str (for Unix sockets)
        """
        try:
            python_cmd = (f"import logging; "
                        f"logging.basicConfig("
                        f"filename='/home/root/data_server.log',"
                        f" format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s',"
                        f" level=logging.DEBUG,"
                        f" filemode='w'); "
                        f"from acadia.data import DataManager; "
                        f"DataManager._server_process_func('{self._output_directory}', ('{address[0]}', {address[1]}));")

            self._server_process = subprocess.Popen(["python3", "-c", python_cmd], 
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, 
                                        stderr=subprocess.PIPE,
                                        preexec_fn=os.setsid)
        except:
            logging.error(f"Exception raised in server process: {traceback.format_exc()}")
 
    def stop_server(self):
        """
        Stop the server and all associated threads.
        """
        with open(os.path.join(self._output_directory, ".stop"), "wb") as f:
            f.write(b'stop plz')
            
        try:
            self._server_process.wait(1)
        except Exception as exc:
            self._server_process.kill()
        
    def server_running(self):
        """
        Check whether or not the server is running.
        
        :rtype: bool
        """
        return (self._server_process is not None
                and self._server_process.poll() is None)
        
    def append(self, group_name, record):
        self._groups[group_name].append(record)
        self._record_count += 1        
        if self._record_count == self._save_count:
            self.save()
        
    def save(self):
        """
        Commit data in all groups to files.
        """   
        logging.debug("Saving records...")
        
        metadata = {"datetime_format": self._datetime_format, 
                    "groups": {}}
        for name,group in self._groups.items():                    
            metadata["groups"][name] =  {
                "type": group.__class__.__name__,
                "length": len(group),
                "files": group.files(),
                "metadata": group.metadata()
            }

            group.save(name, self._output_directory)
                
        for saved_file in self._saved_files:
            metadata["files"].append(saved_file)
                    
        with open(os.path.join(self._output_directory, "metadata.json"), "a+") as file:
            fcntl.fcntl(file, fcntl.F_SETLKW, struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0))
            # logging.debug("Locked metadata")
            
            file.seek(0)
            file.truncate()
            json.dump(metadata, file)
            
            fcntl.fcntl(file, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0))
            # logging.debug("Released metadata")
        
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
        
    def add_group(self, name, group):
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
        
    def _update_progress_file(self):
        with open(os.path.join(self._output_directory, "progress.json"), "a+") as f:
            fcntl.fcntl(f, fcntl.F_SETLKW, struct.pack("hhllhh", fcntl.F_WRLCK, 0, 0, 0, 0, 0))
            # logging.debug("Locked progress")
            
            f.seek(0)
            f.truncate()
            json.dump(self._progress_dict, f)
            
            fcntl.fcntl(f, fcntl.F_SETLK, struct.pack("hhllhh", fcntl.F_UNLCK, 0, 0, 0, 0, 0))
            # logging.debug("Released progress")
            
    def progress_advance(self):
        """
        Notify the internal progress counter to increment by 1.
        """
        
        self._progress_dict["progress"] += 1
        self._update_progress_file()
            
    def progress_complete(self):
        """
        Notify the internal progress counter that data collection is complete.
        """
        self._progress_dict["complete"] = True
        self._update_progress_file()
            
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
        self._progress_dict["total"] = len(it) if hasattr(it, "__len__") else None
        self._progress_dict["progress"] = 0
        self._progress_dict["complete"] = False
        self._update_progress_file()
                
        for item in it:
            yield item
            self.progress_advance()
                
        self.progress_complete()
                