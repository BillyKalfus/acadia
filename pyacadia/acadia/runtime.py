import os
import traceback
import subprocess
import socket
import io
import fcntl
import struct
import time
import datetime
import logging
import pickle
import json
from ipywidgets import Button
from IPython.display import display
from threading import Thread, Event
from abc import ABC, abstractclassmethod, abstractmethod

import numpy as np

from .data import DataManager

__all__ = ["Runtime", "RuntimeReporter", "RuntimeServer"]

class Runtime(ABC):
    """
    An organization class for orchestrating the deployment of programs on 
    remote targets.
    """
    
    # ---------------- Functions to be implemented or overridden by the user ------------- #
    @abstractclassmethod
    def main(cls, directory):
        """
        A function that will be run on the target upon deployment. 
        """
        pass
    
    def plot(self):
        """
        This function should initialize any figures or other graphical objects
        and return a function that will update them along with the primary
        ``Figure`` object. This function must accept a progress dictionary (the
        return value of `DataManager.receive_counters` as its first and only 
        argument.
        """
        return None, None, None 
    
    # ---------------- Functions to be run on the host ---------------- #
    
    def run(self, 
            filename, 
            target_address, 
            remote_server_port=6672,
            remote_base_directory="/home/root", 
            local_temp_directory="/tmp",
            subdirectory_name=None,
            username="root", 
            upload_timeout=5, 
            remote_log_level="DEBUG",
            update_period=0.1):
        """
        Deploy the procedure implemented by :meth:`main` on a remote
        target. A base directory must be supplied, within which a subdirectory 
        will be created for this particular run. This will be used for 
        uploading data and program files, storing logs, and any temporary 
        files. The name of the subdirectory is optional, and if not supplied
        a name is derived from the current date and time.
        
        Progress can be reported from the target back to the host by specifying
        a group 
        
        Deployment is carried out using SSH and a password prompt is not 
        implemented, meaning that key-based authentication must be configured
        on the target prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done once.  
  
        """         
        time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%m%d%y-%H%M%S")
        subdirectory = subdirectory_name if subdirectory_name is not None else time_str
        directory = os.path.join(remote_base_directory, subdirectory)
        temp_directory = os.path.join(local_temp_directory, subdirectory)
        remote_runtime_file = os.path.join(directory, filename)
        
        # Load the code to deploy        
        with open(filename, "r") as file:
            code = file.read()
            
        code += f"\n\n"
        code += f"if __name__ == \"__main__\":\n"
        code += f"    import logging\n"
        code += f"    {self.__class__.__name__}.remote_main(\"{directory}\", {remote_server_port}, logging.{remote_log_level})\n"

        logging.info(f"Creating remote directory {directory} and uploading runtime file")
        cmd = f"ssh {username}@{target_address} \"mkdir {directory}; cat > {remote_runtime_file};\""
        logging.debug(f"Executing command {cmd}")
        file_proc = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
            shell=True)
        stdout,stderr = file_proc.communicate(input=code, timeout=upload_timeout)
        
        if file_proc.returncode != 0:
            logging.error(f"File upload failed with output:\n"
                          f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
            raise Exception("File upload failed")

        logging.info(f"Launching remote process")
        cmd = f"ssh {username}@{target_address} python3 {remote_runtime_file}"
        logging.debug(f"Executing command {cmd}")
        
        self._runtime_proc = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
            shell=True)
                
        def _runtime_monitor():
            stdout,stderr = self._runtime_proc.communicate()
            func = logging.error if stderr != "" else logging.debug
            func(f"Remote runtime process completed with output:\n"
                 f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
        
        self._runtime_monitor_thread = Thread(target=_runtime_monitor,
                                              name="RuntimeMonitorThread",
                                              daemon=True)
        self._runtime_monitor_thread.start()
        
        # Create an event for signalling threads to stop
        self._display_stop_event = Event()
        
        self._server_address = (target_address, remote_server_port)
        
        # Create a new thread for keeping track of display elements and rendering
        logging.debug(f"Creating local temporary directory {temp_directory}")
        os.mkdir(temp_directory)
        
        logging.info(f"Starting local display thread")          
        self._display_thread = Thread(target=Runtime._display, 
                                     name="DisplayThread",
                                     args=(self._display_stop_event, 
                                           self._server_address, 
                                           update_period, 
                                           temp_directory),
                                     daemon=True)
        self._display_thread.start()
        
        self._create_widgets()
        
    def _create_widgets(self):
        
        # Create an overall grid for viewing plots and logs
        # grid = GridspecLayout()
        
        # Create a stop button
        def _self_stop(*args, **kwargs):
            self.stop()
            
        self._stop_button = Button(
            description="Stop", 
            tooltip="Click to stop all local and remote processes.")
        
        self._stop_button.on_click(_self_stop)
        display(self._stop_button)
        
    def stop(self):
        """
        Gracefully stop any running process.
        """
        logging.info("Stopping")
        if self._runtime_proc is None:
            # We never started
            return
        
        self._display_stop_event.set()
        self._display_thread.join()
        
        # Request the server to stop
        RuntimeServer.request_close(self._server_address)
        
        self._stop_button.disabled = True
            
    @staticmethod
    def _display(stop_event, address, update_period, temp_directory):      
        logging.debug("Reporter display thread started")

        mgr = DataManager(temp_directory)   
        initialized_displays = []    
        while True:
            if stop_event.is_set():
                logging.debug("Stopping reporter display")
                return
            
            metadata_string = RuntimeServer.request_metadata(address, raw=True)
            if metadata_string is not None and len(metadata_string) > 0:
                with open(os.path.join(temp_directory, "metadata.json"), "w") as f:
                    f.write(metadata_string)
                
                metadata = json.loads(metadata_string)
                for group_name, group_data in metadata.items():
                    for filename in group_data["files"]:
                        file_path = os.path.join(temp_directory, filename)
                        offset = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                        file_bytes = RuntimeServer.request_file(address, filename, offset)
                        if file_bytes is None:
                            logging.error(f"File {filename} listed in metadata"
                                          " but unable to be retrieved from"
                                          " the server.")
                            continue
                        
                        if len(file_bytes) > 0:
                            with open(file_path, "ab") as f:
                                f.write(file_bytes)
                mgr.load(reload=True)
                
                # logging.debug(f"Manager contains groups {mgr.group_names()}")
                
                for group_name in metadata.keys():
                    if group_name in initialized_displays:
                        mgr[group_name].update_display()
                    else:
                        mgr[group_name].initialize_display()
                        initialized_displays.append(group_name)
                
            time.sleep(update_period)
        
    # ----------------- Functions to be run on the target ----------------- #

    @classmethod
    def remote_main(cls, directory, server_port, log_level):
        """
        This is the main entry point of the remote process. This should not 
        be called manually.
        """
        
        logging.basicConfig(level=log_level, 
                    filename=os.path.join(directory, "remote_main.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')

        
        from multiprocessing import Process
                        
        # Start a RuntimeServer that hosts can use to interact with this target
        logging.info(f"Launching server")
        server_proc = Process(target=RuntimeServer.serve, 
                              args=(directory, ("", server_port)),
                              name="RuntimeServerProcess",
                              daemon=True)
        server_proc.start()
        
        # Run the user main program
        logging.info("Launching main process")
        main_proc = Process(target=cls._main_process,
                            args=(directory, log_level),
                            name="RuntimeMainProcess",
                            daemon=True)
        
        main_proc.start()
        
        # Wait until the server process ends before exiting, as this means 
        # that the host received everything it needed and instructed the server
        # to close
        while server_proc.is_alive():
            # Should there be a delay here? Unclear whether the overhead 
            # associated with checking a Process' state is negligible here...
            pass
                        
        logging.debug("Server process closed, exiting main loop")
        if main_proc.is_alive():
            main_proc.kill()
            
    @classmethod
    def _main_process(cls, directory, log_level):
        """
        Perform some setup and call the user-provided main method.
        """
        logging.basicConfig(level=log_level, 
                    filename=os.path.join(directory, "main_process.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
        try:
            cls.main(directory)
        except:
            logging.error(f"Exception in `main`: {traceback.format_exc()}")        
        
class RuntimeServer:
    """
    A simple server for remotely interacting with :class:`Runtime` instances.
    """
    
    @staticmethod
    def _sendint(sock: socket.socket, i: int):
        """
        Send an integer over a socket.
        """
        sock.sendall(i.to_bytes(8, "little"))
        
    @staticmethod
    def _recvint(sock: socket.socket) -> int:
        """
        Receive an integer from a socket.
        """
        i_bytes = b''
        while len(i_bytes) < 8:
            i_bytes += sock.recv(8 - len(i_bytes))
        return int.from_bytes(i_bytes, "little")
    
    @staticmethod
    def _sendbytes(sock: socket.socket, data: bytes):
        RuntimeServer._sendint(sock, len(data))
        if len(data) > 0:
            sock.sendall(data)
        
    @staticmethod
    def _recvbytes(sock: socket.socket) -> bytes:
        length = RuntimeServer._recvint(sock)
        bytes_received = 0
        data = bytearray(length)
        dataview = memoryview(data)
        
        while bytes_received < length:
            bytes_received += sock.recv_into(dataview[bytes_received:], length-bytes_received)
            
        return data
    
    @staticmethod
    def _sendobj(sock:socket.socket, obj):
        """
        Send a serialized object over a socket.
        """
        if obj is None:
            RuntimeServer._sendint(sock, 100)
        elif isinstance(obj, (np.ndarray, float, complex)):       
            RuntimeServer._sendint(sock, 1)
            npy = io.BytesIO()
            np.save(npy, allow_pickle=False, arr=obj)
            RuntimeServer._sendbytes(sock, npy.getbuffer())
        elif isinstance(obj, str):
            RuntimeServer._sendint(sock, 2)
            RuntimeServer._sendbytes(sock, obj.encode("ascii"))
        elif isinstance(obj, bytes):
            RuntimeServer._sendint(sock, 3)
            RuntimeServer._sendbytes(sock, obj)
        elif isinstance(obj, int):
            RuntimeServer._sendint(sock, 4)
            RuntimeServer._sendint(sock, obj)
        elif isinstance(obj, dict):
            RuntimeServer._sendint(sock, 5)
            npz = io.BytesIO()
            np.savez(npz, allow_pickle=False, **obj)
            RuntimeServer._sendbytes(sock, npz.getbuffer())
        else:
            RuntimeServer._sendint(sock, 10)
            RuntimeServer._sendbytes(sock, pickle.dumps(obj))
            
    @staticmethod
    def _recvobj(sock: socket.socket):
        typecode = RuntimeServer._recvint(sock)
        if typecode == 100:
            # None
            return None
        elif typecode == 1:
            # np array
            npy = RuntimeServer._recvbytes(sock)
            return np.load(io.BytesIO(npy), allow_pickle=False)
        elif typecode == 2:
            # string
            return RuntimeServer._recvbytes(sock).decode("ascii")
        elif typecode == 3:
            # bytes
            return RuntimeServer._recvbytes(sock)
        elif typecode == 4:
            # int
            return RuntimeServer._recvint(sock)
        elif typecode == 5:
            # dict encoded as NPZ
            npz = RuntimeServer._recvbytes(sock)
            return np.load(io.BytesIO(npz), allow_pickle=False)
        elif typecode == 10:
            # pickled stream
            data = RuntimeServer._recvbytes(sock)
            return pickle.loads(data)
    
    @staticmethod
    def _connect_to_server(address):
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
            # logging.debug(f"Failed to connect: {traceback.format_exc()}")
            return None

        # logging.debug(f"Established connection to server {address}")
        
        return s
    
    @staticmethod
    def request_metadata(address, raw=False):
        """
        Request the server to process local data using a designated function.
        
        :param raw: If `True`, the raw bytes of the file will be returned;
            otherwise, it is interpreted as a stream of JSON data and loaded.
        """
        sock = RuntimeServer._connect_to_server(address)
        if sock is None:
            return None
        
        cmd_id = np.random.randint(1e6)
        
        RuntimeServer._sendint(sock, cmd_id)
        RuntimeServer._sendint(sock, 1)
        retval = RuntimeServer._recvobj(sock)
        sock.close()
        
        if retval is None:
            return None
        
        return (retval if raw else json.loads(retval))
    
    @staticmethod
    def request_file(address, filename, offset=0):
        """
        Retrieve reporters from a remote server at a given address.
        
        :param address: Server address
        """
        sock = RuntimeServer._connect_to_server(address)
        if sock is None:
            return None
        
        cmd_id = np.random.randint(1e6)
        
        RuntimeServer._sendint(sock, cmd_id)
        RuntimeServer._sendint(sock, 2)
        RuntimeServer._sendobj(sock, filename)
        RuntimeServer._sendint(sock, offset)
        retval = RuntimeServer._recvobj(sock)
        sock.close()
   
        return retval
    
    @staticmethod
    def request_close(address) -> bool:
        """
        Request the server to close itself.
        
        :param address: Server address
        :return: `True` if the server properly acknowledges the request
        :rtype: bool
        """        
        sock = RuntimeServer._connect_to_server(address)
        if sock is None:
            return None
        
        cmd_id = np.random.randint(1e6)
        
        RuntimeServer._sendint(sock, cmd_id)
        RuntimeServer._sendint(sock, 3)
        retval = RuntimeServer._recvobj(sock)
        sock.close()
        
        if retval != "ack":
            logging.error(f"Received invalid closure acknowledgement"
                          f" (received {retval})")
            return False
        
        return True
      
    @staticmethod
    def serve(file_directory, address, log_level="DEBUG"):
        """
        A function for running a remote process on the target that can provide 
        progress information and pre-processed data. 
        """
        logging.basicConfig(level=getattr(logging, log_level), 
                    filename=os.path.join(file_directory, "server.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
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
        
        logging.debug(f"Started server at {address}")
        
        # Save some file paths as we don't need to recompute them every time
        stop_file_path = os.path.join(file_directory, ".stop")
        metadata_path = os.path.join(file_directory, "metadata.json")
        
        # Continuously accept connections
        while True:
            try:
                conn, addr = s.accept()
                # logging.debug(f"Received connection from {addr}")
                conn.settimeout(1)
            except socket.timeout:
                if os.path.exists(stop_file_path):
                    logging.info("Stop file located, stopping")
                    os.remove(stop_file_path)
                    break
                else:
                    continue
                
            try:
                cmd_id = RuntimeServer._recvint(conn)
                cmd = RuntimeServer._recvint(conn)
                # logging.debug(f"(id {cmd_id}) Received command {cmd}")
                
                if cmd == 1:
                    if os.path.exists(metadata_path):
                        RuntimeServer._sendobj(conn, DataManager.read_metadata(file_directory, raw=True))
                    else:
                        RuntimeServer._sendobj(conn, None)
                        
                elif cmd == 2:
                    filename = RuntimeServer._recvobj(conn)
                    position = RuntimeServer._recvint(conn)
                    file_path = os.path.join(file_directory, filename)
                    if os.path.exists(file_path):
                        size = os.path.getsize(os.path.join(file_directory, filename))
                        if position < size:
                            logging.debug(f"Sending file {filename}"
                                          f" ({position-size} bytes out of"
                                          f" {size} total bytes)")
                            with open(file_path, "rb") as f:
                                f.seek(position)
                                data = f.read()
                        else:
                            data = b''
                            
                        RuntimeServer._sendobj(conn, data)
                    else:
                        RuntimeServer._sendobj(conn, None)    
                    
                elif cmd == 3:
                    logging.debug(f"(id {cmd_id}) Closing server from manual command")
                    with open(stop_file_path, "w+") as f:
                        f.write("stop from client")
                    RuntimeServer._sendobj(conn, "ack")
                        
                else:
                    logging.error(f"(id {cmd_id}) Received invalid command {cmd}")
                    
                # Close the connection and accept a new one
                conn.close()
            except:
                logging.debug(f"Exception in client processing: {traceback.format_exc()}")
                
        s.close()
        
