import os
import traceback
import socket
import io
import logging
import pickle
import json
import shutil

from datetime import datetime, timezone
from threading import Thread, Event
from typing import Tuple, Any, Union
from dataclasses import asdict, is_dataclass
from subprocess import Popen, TimeoutExpired, PIPE
from itertools import count
from abc import ABC, abstractmethod

import io
import matplotlib.pyplot as plt
from IPython.display import Image, display
from matplotlib.animation import Animation

import numpy as np

from .data import DataManager

__all__ = ["Runtime", 
           "RuntimeServer",
           "RuntimeComponent",
           "PyPlotRuntimeComponent"]

class Runtime:
    """
    An organization class for orchestrating the deployment of programs on 
    remote targets.
    """
    
    # ---------------- Functions to be implemented or overridden by the user ------------- #
    def main(self, directory: str, datamanager: DataManager) -> Any:
        """
        A function that will be run on the target upon deployment. 
        """
        raise NotImplemented("Main not implemented")
    
    def initialize(self) -> None:
        """
        This will be called on the host inside of :meth:`deploy` after the
        remote process has been launched but before the event loop starts.
        Add components here!
        """
        pass
    
    # ---------------- Functions to be run on the host ---------------- #
    def deploy(self, 
            target_address: str, 
            filename: str = None,
            remote_server_port: int = 6672,
            remote_base_directory: str = "/home/root", 
            local_base_directory: str = "/tmp",
            subdirectory_name: str = None,
            username: str = "root", 
            log_level=logging.INFO,
            update_period: float = 0.5,
            remove_remote_directory: bool = True,
            **kwargs):
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
        
        Finally, on the target itself one should set "UsePAM no" in 
        ``/etc/ssh/sshd_config`` in order to speed up deployment, but this is
        not required.
  
        """      
        time_str = datetime.now(timezone.utc).strftime("%m%d%y-%H%M%S")
        subdirectory = subdirectory_name if subdirectory_name is not None else time_str
        self.remote_directory = os.path.join(remote_base_directory, subdirectory)
        self.local_directory = os.path.join(local_base_directory, subdirectory)
        
        self._username = username
        self._target_address = target_address
        self._remove_remote_directory = remove_remote_directory
        self._local_log_name = os.path.join(self.local_directory, "runtime.log")
        self._log_level = log_level

        os.mkdir(self.local_directory)
        
        logging.basicConfig(level=log_level, 
                    filename=self._local_log_name, 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
        self._create_widgets()

        self.login = f"{username}@{target_address}"
        
        self._status.value = "Status: Preparing files"
        logging.debug(self._status.value)
        runfile_name = self._prepare_files(filename, log_level, kwargs)

        self._status.value = "Status: Deploying files"
        logging.debug(self._status.value)
        Runtime._deploy_files(self.local_directory, self.login, remote_base_directory)
        remote_runfile = os.path.join(self.remote_directory, runfile_name)

        self._status.value = "Status: Starting remote runtime"
        logging.debug(self._status.value)
        self._runtime_proc = Runtime._run_remote_runfile(self.login, remote_runfile)

        self._status.value = "Status: Starting remote server"
        logging.debug(self._status.value)
        self._server_proc = RuntimeServer.deploy(self.login, self.remote_directory, remote_server_port, log_level)
        
        self._stop_flag = Event()
        self._server_address = (target_address, remote_server_port)
        self.local_data_manager = DataManager(self.local_directory)
        
        self._status.value = "Status: Starting event loop"
        logging.debug(self._status.value)
        self._event_loop = self._create_event_loop(update_period, 0.2, self._server_address)
        self._event_loop.start()

        self._components = []

        logging.debug("Deployment complete")

    def request_stop(self, timeout=2):
        self._status.value = "Status: Requesting event loop stop"
        self._stop_flag.set()
        try: 
            self._event_loop.join(timeout=timeout)
        except:
            logging.error("Event loop thread did not join, manually stopping")
            self.stop()

    def stop(self, timeout=1):
        Runtime._stop_remote(self.login,
                        self.local_directory,
                        self.remote_directory,
                        self._runtime_proc, 
                        self._server_proc, 
                        self._server_address, 
                        timeout)
        
        self._stop_button.disabled = True
        self._remote_log_link.value = f"<a href=\"{os.path.join(self.local_directory, 'remote_main.log')}\">Remote Log</a>"

        if self._remove_remote_directory:
            self._status.value = "Status: Removing remote directory"
            logging.debug(self._status.value)

            cmd = f"ssh {self.login} rm -r {self.remote_directory}"
            os.system(cmd)

        self._status.value = "Status: Stopped"
        logging.debug(self._status.value)
    
    def update(self) -> None:
        """
        This function will be called inside of :meth:`deploy` during the 
        event loop every time the host receives new data from the remote 
        process. If no data is ever received, it will never be called, and
        if the host continuously receives data, it may be called many times.
        """
        for component in self._components:
            component.update()

    def finalize(self) -> None:
        """
        This will be called inside of :meth:`deploy` once the event loop exits.
        """
        for component in self._components:
            component.finalize()

    def add_component(self, component_type, *args, **kwargs):
        """
        Add a component to the runtime.
        """
        component = component_type(self, *args, **kwargs)
        self._components.append(component)

    @property
    def data(self):
        return self.local_data_manager

    def _save_args(self, directory: str, **kwargs) -> str:
        """
        Save all necessary arguments into a file in the given directory.
        """
        filename = os.path.join(directory, "kwargs.npz")
        np.savez(file=filename, **kwargs)
        return filename

    @staticmethod
    def _load_args(directory: str) -> dict:
        """
        Load saved arguments. 
        """
        path = os.path.join(directory, "kwargs.npz")
        if not os.path.exists(path):
            return {}
        
        data = np.load(path).items()
        return {k:(v[()].item() if v.ndim == 0 else v) for k,v in data}
    
    def _prepare_files(self, runtime_filename, log_level, kwargs):
        if runtime_filename is not None:
            local_filepath = runtime_filename
        elif hasattr(self, "FILENAME"):
            local_filepath = self.FILENAME
        else:
            raise ValueError("Unable to identify file path for deployment")
        
        runfile_name = os.path.basename(local_filepath)
        local_runtime_file = os.path.join(self.local_directory, runfile_name)
        shutil.copy2(local_filepath, local_runtime_file)     
        with open(local_runtime_file, "a") as file:
            file.write(f"\n\n")
            file.write(f"if __name__ == \"__main__\":\n")
            file.write(f"    from acadia.runtime import Runtime\n")
            file.write(f"    kwargs = Runtime._load_args(\"{self.remote_directory}\")\n")
            file.write(f"    runtime = {self.__class__.__name__}(**kwargs)\n")
            file.write(f"    runtime.run(\"{self.remote_directory}\", {log_level})\n")
    
        logging.debug("Aggregating arguments")
        if is_dataclass(self):
            kwargs.update(asdict(self))
        if hasattr(self, "__getstate__"):
            tmp = self.__getstate__()
            if not isinstance(tmp, dict):
                raise TypeError("Runtime objects that implement `__getstate__` must"
                                f" return a dict (received {type(tmp)})")
            kwargs.update(tmp)

        if len(kwargs) != 0:
            logging.debug(f"Saving arguments")
            self._save_args(self.local_directory, **kwargs)
        else:
            logging.warning("No arguments found!")

        return runfile_name
    
    @staticmethod
    def _deploy_files(local_directory, login, remote_base_directory):
        logging.info(f"Uploading runtime directory")
        cmd = f"scp -r {local_directory} {login}:{remote_base_directory}"
        logging.debug(f"Executing command {cmd}")
        os.system(cmd)

    @staticmethod
    def _run_remote_runfile(login, remote_runfile):
        logging.info(f"Launching main remote process")
        cmd = f"ssh {login} python3 -t -t {remote_runfile}"
        logging.debug(f"Executing command {cmd}")
        
        return Popen("exec " + cmd, stdout=PIPE, stderr=PIPE,
            text=True, encoding="ascii", shell=True, preexec_fn=os.setsid)
    
    def _create_event_loop(self, update_period: float, timeout: float, server_address: tuple) -> Thread:
                
        def _func():
            import time

            self._status.value = "Status: Initializing event loop"
            logging.debug(self._status.value)
            self.initialize()

            self._status.value = "Status: Event loop running"
            logging.debug(self._status.value)

            while True:
                if self._stop_flag.is_set():
                    logging.debug("Stop requested")
                    break
                try:
                    # Exit the loop if we get output because that means
                    # everything is finished
                    logging.debug("Checking runtime for completion")
                    stdout,stderr = self._runtime_proc.communicate(timeout=timeout)
                    logging.info(f"Main process completed with output:\n"
                            f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
                    break
                except TimeoutExpired:
                    pass
                
                # Update any processing
                try:
                    logging.debug("Checking remote server for new data")
                    updated = RuntimeServer.update_data_manager(self.local_data_manager, server_address)
                    if updated:
                        self.update()
                except:
                    logging.error(f"Exception updating DataManager: {traceback.format_exc()}")

                time.sleep(update_period)

            self._status.value = "Status: Performing final update"
            logging.debug(self._status.value)
            try:
                updated = RuntimeServer.update_data_manager(self.local_data_manager, server_address)
                if updated:
                    self.update()
            except:
                logging.error(f"Exception updating DataManager: {traceback.format_exc()}")

            self._status.value = "Status: Finalizing event loop"
            logging.debug(self._status.value)
            try:
                self.finalize()
            except:
                logging.error(f"Exception during finalization: {traceback.format_exc()}")

            self.stop()
            
        thread = Thread(target=_func,
                        name="EventLoopThread",
                        daemon=True)
        return thread
        
    def _create_widgets(self):
        from IPython.display import display
        from ipywidgets import Button, HTML, HBox
        
        # Create an overall grid for viewing plots and logs
        # grid = GridspecLayout()
        
        # Create a stop button
        def _self_stop(*args, **kwargs):
            self.request_stop()
            
        self._stop_button = Button(
            description="Stop", 
            tooltip="Click to stop all local and remote processes.")
        
        self._stop_button.on_click(_self_stop)
        self._status = HTML(value=f"")
        self._metadata_link = HTML(value=f"<a href=\"{os.path.join(self.local_directory, 'metadata.json')}\">Metadata</a>")
        self._local_log_link = HTML(value=f"<a href=\"{self._local_log_name}\">Local Log</a>")
        self._remote_log_link = HTML(value=f"Remote Log")
        box = HBox([self._stop_button, self._status, self._metadata_link, self._local_log_link, self._remote_log_link])
        display(box)

    @staticmethod
    def _retrieve_remote_log(login, remote_directory, local_directory):
        logging.debug("Retrieving remote log")
        remote_logfile = os.path.join(remote_directory, 'remote_main.log')
        local_logfile = os.path.join(local_directory, 'remote_main.log')
        os.system(f"scp {login}:{remote_logfile} {local_logfile}")

    @staticmethod
    def _stop_remote(login: str,
                    local_directory: str,
                    remote_directory: str,
                    runtime_proc: Popen, 
                    server_proc: Popen, 
                    server_address: tuple, 
                    timeout: float = 1) -> None:
        """
        Gracefully stop a deployed Runtime.
        """
        if runtime_proc is None:
            # We never started
            return
        
        # Wait for the main process to stop
        logging.debug("Stopping remote process")
        try: 
            runtime_proc.wait(timeout=timeout)
        except:
            logging.error("Runtime process did not end; killing it")
            runtime_proc.kill()
        
        # Request the server to stop
        logging.debug("Closing remote server")
        RuntimeServer.request_close(server_address)
        try:
            server_proc.wait(timeout=timeout)
            stdout,stderr = server_proc.communicate()
            func = logging.error if stderr != "" else logging.debug
            func(f"Server process completed with output:\n"
                 f"stdout:\n{stdout}\n\nstderr:\n{stderr}\n\n")
        except:
            logging.error("Server process did not terminate; killing it")
            server_proc.kill()

        Runtime._retrieve_remote_log(login, remote_directory, local_directory)
        
    # ----------------- Functions to be run on the target ----------------- #

    def run(self, directory, log_level=logging.INFO):
        """
        This is the main entry point of the remote process. This should not 
        be called manually unless executed on the target itself.
        """
        import os
        from acadia.data import DataManager
        
        logging.basicConfig(level=log_level, 
                    filename=os.path.join(directory, "remote_main.log"), 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
        
        if not os.path.exists(directory):
            logging.info(f"Creating output directory {directory}")
            try:
                os.mkdir(directory)
            except:
                logging.error(f"Exception creating output directory {directory}:"
                            f" {traceback.format_exc()}")
            
        os.chdir(directory)

        logging.debug(f"Creating DataManager")
        mgr = DataManager(directory=directory)

        logging.info("Running main method")
        try:
            self.main(directory, mgr)
        except:
            logging.error(f"Exception in `main`: {traceback.format_exc()}")

        logging.info("Main complete, saving")
        mgr.save()
        logging.info("Saved")
        
        
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
    def _sendobj(sock: socket.socket, obj):
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
            logging.debug(f"Failed to connect: {traceback.format_exc()}")
            return None

        logging.debug(f"Established connection to server {address}")
        return s
    
    @staticmethod
    def deploy(login, remote_directory, port, log_level):
        logging.info(f"Deploying RuntimeServer on port {port} as {login}")
        cmd = (f"ssh {login} -t -t \"python3 -c \'"
            f"from acadia.runtime import RuntimeServer; "
            f"RuntimeServer.serve(\\\"{remote_directory}\\\", (\\\"\\\", {port}), {log_level});\'\"")
        logging.debug(f"Executing command {cmd}")
        
        _proc = Popen(
            "exec " + cmd, 
            stdout=PIPE, 
            stderr=PIPE,
            text=True,
            encoding="ascii",
            shell=True)
        
        return _proc
    
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
        logging.debug(f"Requesting file {filename} from {address}"
                      f" at offset {offset} and size {size}")
        
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
    def update_data_manager(data_manager: DataManager, 
                            server_address: str) -> bool:
        """
        Update the contents of a DataManager from a RuntimeServer running at 
        an address.

        :param data_manager: manager to update
        :type data_manager: :class:`DataManager`
        :param server_address: Address of the server
        :type server_address: str
        :return: `True` if the manager was updated
        """
        metadata_string = RuntimeServer.request_metadata(server_address, raw=True)
        if metadata_string is None or len(metadata_string) == 0:
            logging.debug(f"Received invalid metadata {metadata_string}")
            return False
        
        with open(os.path.join(data_manager._directory, "metadata.json"), "w") as f:
            f.write(metadata_string)
        
        metadata = json.loads(metadata_string)
        filedeltas = data_manager.filedeltas(metadata)
        logging.debug(f"Received deltas {filedeltas}")
        
        updated = False
        for filename,(offset,size) in filedeltas.items():
            if size == 0:
                continue                
            
            file_path = os.path.join(data_manager._directory, filename)
            file_bytes = RuntimeServer.request_file(server_address, filename, offset, size)
            if file_bytes is None:
                logging.error(f"File {filename} listed in metadata"
                                " but unable to be retrieved from"
                                " the server.")
                continue
            
            if len(file_bytes) > 0:
                updated = True
                logging.debug(f"Writing {len(file_bytes)} bytes to {file_path} at offset {offset}")
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
            else:
                logging.error(f"Received filedelta for file"
                                f" {filename} with size {size} but"
                                f" server returned no file data")
                    
        data_manager.load(reload=True)
        return updated

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
        
        logging.info(f"Started server at {address}")
        
        # Save some file paths as we don't need to recompute them every time
        stop_file_path = os.path.join(file_directory, ".stop")
        metadata_path = os.path.join(file_directory, "metadata.json")
        
        # Continuously accept connections
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
                cmd_id = RuntimeServer._recvint(conn)
                cmd = RuntimeServer._recvint(conn)
                logging.debug(f"(id {cmd_id}) Received command {cmd}")
                
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
    
class RuntimeComponent(ABC):

    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    @abstractmethod
    def update(self):
        pass

    def finalize(self):
        self.update()

class PyPlotRuntimeComponent(RuntimeComponent):

    def create_plot(self):
        pass

    def update_plot(self):
        pass

    def __init__(self, runtime: Runtime):
        super().__init__(runtime)
        
        self.fig = plt.figure()
        self.create_plot()
        
        def _init(anim_self: Animation, *args, **kwargs):
            anim_self._framedata = count()
            super(anim_self.__class__, anim_self).__init__(*args, **kwargs)
        
        def _update(animation, framedata):
            self.update_plot()

        test_animation_type = type(f"RuntimePyPlotAnimation", 
                                (Animation,), 
                                {"__init__": _init, 
                                 "_draw_frame": _update})

        def _dummy(*args, **kwargs):
            pass
        
        DummyEvent = type("DummyEvent", (), {"add_callback": _dummy, "start": _dummy, "stop": _dummy})

        self.anim = test_animation_type(self.fig, event_source=DummyEvent)
        self.anim._step()
    
    def update(self):        
        self.anim._step()
        
    def finalize(self):
        self.update()
        
        buf = io.BytesIO()
        self.fig.savefig(buf, format="png", dpi=400)
        plt.ioff()
        
        # buf.seek(0)
        # img = Image(data=buf.read(), format="png", embed=True, width=720)
        # display(img)

    def figure(self):
        return self.fig
        
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

class CounterRuntimeComponent(RuntimeComponent):
    def __init__(self, runtime: Runtime, record_name: str):
        super().__init__(runtime)
        
        self._record_name = record_name

        from tqdm.notebook import tqdm
        self.bar = tqdm(desc=self._record_name, dynamic_ncols=True)
        self._last_count = 0

    def update(self):
        group = self.runtime.data[self._record_name]
        if "total" in group.metadata():
            self.bar.total = group.total
            self.bar.refresh()

        self.bar.update(group.count - self._last_count)
        self._last_count = group.count
            
    def finalize(self):
        self.update()
        self.bar.close()
