import os
import traceback
import subprocess
import socket
import io
import time
import datetime
import logging
import pickle
import json

from threading import Thread, Event
from abc import ABC, abstractclassmethod

import numpy as np

from .data import DataManager, DisplayMixin

__all__ = ["Runtime", "RuntimeServer"]

class Runtime(ABC):
    """
    An organization class for orchestrating the deployment of programs on 
    remote targets.
    """
    
    # ---------------- Functions to be implemented or overridden by the user ------------- #
    @abstractclassmethod
    def main(cls, directory: str, datamanager: DataManager, kwargs: dict):
        """
        A function that will be run on the target upon deployment. 
        """
        pass
    
    def plot(self, fig):
        """
        This function should initialize any figures or other graphical objects
        and return a function that will update them along with the primary
        ``Figure`` object. This function must accept a progress dictionary (the
        return value of `DataManager.receive_counters` as its first and only 
        argument.
        """
        return None, None, None 
    
    # ---------------- Functions to be run on the host ---------------- #
    
    def __init__(self, kwargs):
        """
        Create a local instance of the runtime
        """
        self._kwargs_json = json.dumps(kwargs)
    
    def run(self, 
            target_address, 
            filename=None,
            remote_server_port=6672,
            remote_base_directory="/home/root", 
            local_download_directory="/tmp",
            subdirectory_name=None,
            username="root", 
            display=True,
            upload_timeout=5, 
            log_level=logging.DEBUG,
            update_period=0.5,
            multiplex_ssh=False,
            remove_remote_directory=True,
            copy_to_local=True):
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
        
        Because SSH is used for performing all remote operations, one can 
        significantly speed up deployment using SSH multiplexing. To set this
        up, open a terminal and execute the following:

            ``ssh -o "ControlMaster=yes" -o "ControlPath=~/.ssh/controlmasters/%r@%h:%p" <username>@<target>``
            
        This will open a new SSH terminal with the added feature that any new
        SSH connections will be multiplexed through this existing one, 
        eliminating the need to reauthenticate every time. 
        
        Finally, on the target itself one should set "UsePAM no" in 
        ``/etc/ssh/sshd_config``.
  
        """      
        time_str = datetime.datetime.now(datetime.timezone.utc).strftime("%m%d%y-%H%M%S")
        subdirectory = subdirectory_name if subdirectory_name is not None else time_str
        self.remote_directory = os.path.join(remote_base_directory, subdirectory)
        self.local_directory = os.path.join(local_download_directory, subdirectory)
        
        self._username = username
        self._target_address = target_address
        self._copy_to_local = copy_to_local
        self._remove_remote_directory = remove_remote_directory
        
        os.mkdir(self.local_directory)
        
        logging.basicConfig(level=log_level, 
                    filename=os.path.join(self.local_directory, "runtime.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
        if filename is not None:
            local_filepath = filename
        elif hasattr(self, "FILENAME"):
            local_filepath = self.FILENAME
        else:
            raise ValueError("Unable to identify file path for deployment")
        
        remote_runtime_file = os.path.join(self.remote_directory, 
                                           os.path.basename(local_filepath))
        
        # Load the code to deploy        
        with open(local_filepath, "r") as file:
            code = file.read()
            
        code += f"\n\n"
        code += f"if __name__ == \"__main__\":\n"
        code += f"    import json\n"
        code += f"    kwargs = json.loads('{self._kwargs_json}')\n"
        code += f"    {self.__class__.__name__}.remote_main(\"{self.remote_directory}\", {log_level}, kwargs)\n"

        multiplex_flags = ""
        if multiplex_ssh:
            control_masters_path = os.path.expanduser("~/.ssh/controlmasters")
            if os.path.exists(control_masters_path):
                multiplex_flags = f"-o \"ControlPath={os.path.join(control_masters_path, '%r@%h:%p')}\""
                logging.debug("Using SSH multiplexing")
            else:
                logging.warning("Connection attempted to use SSH multiplexing"
                                " but no control master directory found.")
            
            
        ssh_cmd = f"ssh {multiplex_flags} {username}@{target_address}"

        logging.info(f"Creating remote directory {self.remote_directory} and uploading runtime file")
        cmd = f"{ssh_cmd} \"mkdir {self.remote_directory}; cat > {remote_runtime_file};\""
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

        logging.info(f"Launching main remote process")
        cmd = f"{ssh_cmd} -t -t python3 {remote_runtime_file}"
        logging.debug(f"Executing command {cmd}")
        
        self._runtime_proc = subprocess.Popen(
            "exec " + cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
            shell=True,
            preexec_fn=os.setsid)
        
        logging.info(f"Launching remote server")
        cmd = (f"{ssh_cmd} -t -t \"python3 -c \'"
            f"from acadia.runtime import RuntimeServer; "
            f"RuntimeServer.serve(\\\"{self.remote_directory}\\\", (\\\"\\\", {remote_server_port}), {log_level});\'\"")
        logging.debug(f"Executing command {cmd}")
        
        self._server_proc = subprocess.Popen(
            "exec " + cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
            shell=True)
        
        self._runtime_monitor_stop_flag = Event()
                
        def _runtime_monitor():
            while True:
                if self._runtime_monitor_stop_flag.is_set():
                    return 
                try:
                    stdout,stderr = self._runtime_proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            
            func = logging.error if stderr != "" else logging.debug
            func(f"Main process completed with output:\n"
                 f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
            self.stop()
        
        self._runtime_monitor_thread = Thread(target=_runtime_monitor,
                                              name="RuntimeMonitorThread",
                                              daemon=True)
        self._runtime_monitor_thread.start()
        
        self._server_address = (target_address, remote_server_port)
        
        # Create a new thread for keeping track of display elements and rendering
        # Create an event for signalling threads to stop
        self._display_stop_event = Event()
        self._display_iteration_event = Event()
        
        if display:
            logging.info(f"Starting local display thread")          
            self._display_thread = Thread(target=Runtime._display, 
                                        name="DisplayThread",
                                        args=(self._display_stop_event,
                                            self._display_iteration_event, 
                                            self._server_address, 
                                            update_period, 
                                            self.local_directory),
                                        daemon=True)
            self._display_thread.start()
        else:
            self._display_thread = None
        
        self._create_widgets()
        
        return subdirectory
        
    def _create_widgets(self):
        from IPython.display import display
        from ipywidgets import Button
        
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
        
    def stop(self, timeout=1):
        """
        Gracefully stop any running process.
        """
        logging.info("Stopping")
        if self._runtime_proc is None:
            # We never started
            return
        
        # Allow the display thread to complete one more full iteration
        # in case the main process finished before the display thread 
        # could process it
        # We'll need to await the flag twice; first because we'll clear it in the
        # middle of an iteration and itll then get set at the end of the iteration
        # Then, we'll clear it as soon as it's set, and when it's set again, a full
        # iteration will have passed since entering stop()
        if self._display_thread is not None:
            for i in range(4):
                self._display_iteration_event.clear()
                if self._display_iteration_event.wait(timeout=timeout):
                    logging.warning(f"Display thread did set iteration flag on pass {i}")
                else:
                    logging.error(f"Display thread did not set iteration flag on pass {i}")
            
            self._display_stop_event.set()
            try:
                self._display_thread.join(timeout=timeout)
            except:
                logging.error("Display thread did not join")
        
        # Request the server to stop
        RuntimeServer.request_close(self._server_address)
        try:
            self._server_proc.wait(timeout=timeout)
            stdout,stderr = self._server_proc.communicate()
            func = logging.error if stderr != "" else logging.debug
            func(f"Server process completed with output:\n"
                 f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
        except:
            logging.error("Server process did not terminate; killing it")
            self._server_proc.kill()
            
        # Wait for the main process to stop
        try: 
            self._runtime_proc.wait(timeout=timeout)
        except:
            self._runtime_proc.kill()
            
        # Stop the runtime monitor thread
        self._runtime_monitor_stop_flag.set()
        try:
            self._runtime_monitor_thread.join(timeout=timeout)
        except:
            logging.error("Runtime monitor thread did not join")
            
        # Copy the remote directory locally
        if self._copy_to_local:
            logging.debug(f"Copying data from {self.remote_directory} to {self.local_directory}")
            os.system(f"scp {self._username}@{self._target_address}:{self.remote_directory}/* {self.local_directory}")
            logging.debug(f"Copied")
            
        if self._remove_remote_directory:
            os.system(f"ssh {self._username}@{self._target_address} rm -rf {self.remote_directory}")
        
        self._stop_button.disabled = True
            
    @staticmethod
    def _display(stop_event, iteration_event, address, update_period, temp_directory):    
        logging.debug("Display thread started")

        mgr = DataManager(temp_directory)   
        initialized_display_retvals = {}  
        while True:
            try:
                if stop_event.is_set():
                    logging.debug("Stopping display thread")
                    for group_name in mgr.group_names():
                        if isinstance(mgr[group_name], DisplayMixin) and group_name in initialized_display_retvals:
                            try:
                                mgr[group_name].close_display(initialized_display_retvals[group_name])
                            except:
                                logging.error(f"Exception in display close"
                                            f" for group {group_name}: {traceback.format_exc()}")
                    return
                
                metadata_string = RuntimeServer.request_metadata(address, raw=True)
                if metadata_string is not None and len(metadata_string) > 0:
                    with open(os.path.join(temp_directory, "metadata.json"), "w") as f:
                        f.write(metadata_string)
                    
                    metadata = json.loads(metadata_string)
                    filedeltas = mgr.filedeltas(metadata)
                    # logging.debug(f"Received deltas {filedeltas}")
                    
                    for filename,(offset,size) in filedeltas.items():
                        if size == 0:
                            continue
                        
                        file_path = os.path.join(temp_directory, filename)
                        file_bytes = RuntimeServer.request_file(address, filename, offset, size)
                        if file_bytes is None:
                            logging.error(f"File {filename} listed in metadata"
                                            " but unable to be retrieved from"
                                            " the server.")
                            continue
                        
                        if len(file_bytes) > 0:
                            # logging.debug(f"Writing {len(file_bytes)} bytes")
                            if os.path.exists(file_path):
                                with open(file_path, "r+b") as f:
                                    f.seek(offset)
                                    f.write(file_bytes)
                            else:
                                if offset != 0:
                                    raise ValueError(f"Attempted to write to"
                                                     f" non-existent file at"
                                                     f" offset {offset}")
                                with open(file_path, "wb") as f:
                                    f.write(file_bytes)
                                
                    mgr.load(reload=True)
                    
                    # logging.debug(f"Manager contains groups {mgr.group_names()}")
                    
                    for group_name in metadata.keys():
                        if isinstance(mgr[group_name], DisplayMixin):
                            if group_name in initialized_display_retvals:
                                try:
                                    mgr[group_name].update_display(initialized_display_retvals[group_name])
                                except:
                                    logging.error(f"Exception in display initialization"
                                                f" for group {group_name}: {traceback.format_exc()}")
                                    stop_event.set()
                            else:
                                try:
                                    initialized_display_retvals[group_name] = mgr[group_name].initialize_display()
                                except:
                                    logging.error(f"Exception in display update for"
                                                f" group {group_name}: {traceback.format_exc()}")
                                    stop_event.set()
                elif not iteration_event.is_set():
                    logging.warning(f"Noticed main iteration event cleared; got metadata {metadata_string}")            
                
                iteration_event.set()    
            except:
                logging.error(f"Exception in display thread: {traceback.format_exc()}")
                
            time.sleep(update_period)
        
    # ----------------- Functions to be run on the target ----------------- #

    @classmethod
    def remote_main(cls, directory, log_level, kwargs):
        """
        This is the main entry point of the remote process. This should not 
        be called manually.
        """
        
        logging.basicConfig(level=log_level, 
                    filename=os.path.join(directory, "remote_main.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
        try:
            from acadia.data import DataManager
            mgr = DataManager(directory=directory)
            logging.info("Running main method")
            cls.main(directory, mgr, kwargs)
            logging.info("Main complete, saving")
            mgr.save()
            logging.info("Saved")
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
            try:
                i_bytes += sock.recv(8 - len(i_bytes))
            except socket.timeout:
                raise TimeoutError(f"Timed out receiving integer (received {len(i_bytes)} bytes of 8)")
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
            try:
                bytes_received += sock.recv_into(dataview[bytes_received:], length-bytes_received)
            except socket.timeout:
                raise TimeoutError(f"Timed out receiving bytes (received {bytes_received} bytes of {length})")
        
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
        s.settimeout(1)
        
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
    def request_file(address, filename, offset=0, size=0):
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
        RuntimeServer._sendint(sock, size)
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
    def serve(file_directory, address, log_level=logging.DEBUG):
        """
        A function for running a remote process on the target that can provide 
        progress information and pre-processed data. 
        """
        logging.basicConfig(level=log_level, 
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
        s.settimeout(1)
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
                    size = RuntimeServer._recvint(conn)
                    file_path = os.path.join(file_directory, filename)
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            f.seek(position)
                            data = f.read(size if size != 0 else None)
                    else:
                        data = None    
                        
                    RuntimeServer._sendobj(conn, data)
                    
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
        
