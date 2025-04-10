import os
import traceback
import logging
import json
import shutil
import pickle

from datetime import datetime
from threading import Thread, Event, Lock
from typing import Any, Dict, get_type_hints, Union
from subprocess import PIPE, run
from binascii import hexlify, unhexlify
from io import BytesIO


import numpy as np
from numpy.lib.format import write_array, read_array

from acadia.data import DataManager

__all__ = ["Runtime"]

class Runtime:
    """
    An orchestrated deployment of a program on a remote target.

    Subclasses of :class:`Runtime` are expected to be created for each workflow
    a user may want. The :meth:`deploy` method allows a host machine (the one 
    that the user is actively logged into and using as an interface to the
    instrumentation) to remotely deploy a procedure on a remote machine, as 
    specified by the subclass' implementation of :meth:`main`. Meanwhile, on the
    host, a custom event loop runs in a background thread for monitoring the
    remote process' status and retrieving data files.

    Three callback functions may be used to implement dynamic behavior while the
    remote process is still running: :meth:`initialize`, :meth:`update`, and 
    :meth:`finalize`; see their documentation for descriptions of when they are
    triggered. These functions, along with :meth:`main`, form a complete set of
    functions that the user may be expected to override to fully describe a
    workflow.

    When a :class:`Runtime` is deployed, its fields are serialized into a JSON
    file and sent to the target, where a "field" is defined as any class member 
    with a type annotation.
    """
    
    # ---------------- Functions to be implemented or overridden by the user ------------- #
    def main(self) -> Any:
        """
        A function that will be run on the target upon deployment. 
        """
        raise NotImplemented("Main not implemented")
    
    def initialize(self) -> None:
        """
        A callback run on the host just before the event loop is started.
        """
        pass

    def update(self) -> None:
        """
        A callback run on the host when the internal :class:`DataManager` 
        metadata is updated with new data. More specifically, this is called
        when the file modification time of ``metadata.json`` has changed.
        """
        pass

    def finalize(self) -> None:
        """
        A callback run on the host when the event loop has ended. Note that 
        this will be carried out after any final updates have been performed,
        so any data available at the time of this invocation will be the 
        complete set of available data.
        """
        pass
    
    # ---------------- Core functions for interaction from the host ---------------- #

    def __init__(self, **kwargs):
        """
        Create the runtime with the provided values for fields.
        """
        fields = self._get_fields()

        # Make sure that all the provided keywords are valid
        for name,arg in kwargs.items():
            if name not in fields:
                raise KeyError(f"Keyword argument {name} does not refer to "
                                f"any fields of class {self.__class__.__name__}")
            setattr(self, name, arg)

        for name in fields.keys():
            if not hasattr(self, name):
                raise AttributeError(f"Runtime missing value for field {name}")
    
    @classmethod
    def load(cls, directory):
        """
        Load a runtime from a directory on either the host or the target.
         
        If the directory contains ``metadata.txt``, a new :class:`DataManager` 
        is created that wraps the
        data in the directory without overwriting anything. This allows the 
        user to "reload" data from a previous deployment (along with any 
        hierarchical structure to it) and interact with it as if it had just 
        been collected. 

        Together, these behaviors mean that if a user implements all of their 
        data processing as functions that operate on :class:`DataManager` 
        objects and their :class:`RecordGroup` objects, any analysis can be 
        seamlessly performed both in real-time and retroactively.
        """
        logger = logging.getLogger("acadia")

        kwargs_path = os.path.join(directory, "kwargs.json")
        if os.path.exists(kwargs_path):
            logger.debug(f"Loading kwargs from {kwargs_path}")
            with open(kwargs_path, "r") as f:
                kwargs = Runtime._untransform_arg(json.load(f))
        else:
            logger.warning(f"No kwargs.json file found in directory {directory}")
            kwargs = {}
        
        inst = cls(**kwargs)
        inst.data_manager = DataManager()
        try:
            inst.data_manager.load(directory)
        except FileNotFoundError as e:
            logger.warning(f"Unable to load DataManager from directory {directory}")
            pass
        except Exception as e:
            raise e

        return inst

    def deploy(self, 
            target_address: str, 
            runtime_module: str = None,
            files: list[str] = None,
            remote_directory: str = "/tmp/%y%m%d_%H%M%S", 
            local_directory: str = "/tmp/%y%m%d_%H%M%S",
            username: str = "root", 
            log_debug: bool = False,
            event_loop_period: float = 0.25,
            update_lock_timeout: float = 5,
            remove_remote_directory: bool = True,
            multiplex_control_path: str = None,
            do_initialize: bool = True,
            do_update: bool = True,
            do_finalize: bool = True,
            finalization_time: float = 10) -> None:
        """
        Deploy the procedure implemented by :meth:`main` on a remote
        target. 

        A new unique directory (the "execution directory") is created on the
        target every time this method is called, which is used to store
        necessary runtime files, logs for the deployment, and collected data.
        The execution directory will be created on the target within a 
        base directory specified by ``remote_base_directory``. If the 
        deployment is expected to collect a large amount of data, care should
        be taken to ensure that the remote base directory has sufficient free
        space for storing the results.

        Throughout the lifetime of the execution, various files are transferred
        to the host from the target and stored in a local execution directory.
        When execution completes successfully, the local execution directory
        will contain a copy of the remote execution directory, which may be 
        safely deleted (and will be done so automatically if ``remove_remote_directory=True``).
        
        Deployment is carried out using SSH and a password prompt is not 
        implemented, meaning that key-based authentication must be configured
        on the target prior to deployment. This is automatically carried out
        when deploying acadia onto a target using the ``misc/remote_install.sh`` 
        script.
            
        on the host. This only needs to be done when the target does not
        already contain a copy of the host's key, such as when the target
        is used for the first time or when the target's key storage is reset
        (for Acadia hardware, this occurs when the system is power cycled). 
        :param target_address: IP address of the target
        :type target_address: str
        :param runtime_module: Name of the :class:`Runtime` subclass. This is 
            directly used in an ``import`` statement as 
            ``from <runtime_module> import <this class name>``. 
            If ``None``, the current class' module path and name is used.
        :type runtime_module: str
        :param files: Files to be deployed to the target for use during the
            :class:`Runtime` execution. This should be a list and each element,
            which can be either a string or a tuple, will correspond to one 
            file to deploy to the target. If a string, this should be the path
            of the file on the host and it will be copied into the execution
            directory with the same basename. If a tuple, the first element
            should be a string corresponding to the path of the file on the
            host, and the second element should be a new basename that the 
            file will be renamed to when placed into the execution directory.
        :type files: list of str and/or tuple
        :param remote_directory: Execution directory on the target. This will
            be passed as an argument to :meth:`datetime.strftime`
        :type remote_directory: str
        :param local_directory: Execution directory on the host. This will
            be passed as an argument to :meth:`datetime.strftime`
        :type local_directory: str
        :param username: Name of remote user used for login
        :type username: str
        :param log_debug: If ``True``, logging is set to include debug 
            messages.
        :type log_debug: bool
        :param event_loop_period: The event loop will ensure that at least this 
            much time has passed in between requests from the target. 
        :type event_loop_period: float
        :param remove_remote_directory: If ``True``, the directory will be
            deleted from the target once execution is complete.
        :type remove_remote_directory: bool
        :param multiplex_control_path: The path for storing control master
            sockets for multiplexed SSH connections
        :type multiplex_control_path: str
        :param do_initialize: If ``True``, this class' :meth:`initialize` 
            method is called just before entering the event loop
        :type do_initialize: bool
        :param do_update: If ``True``, this class' :meth:`update` 
            method is called when new data is available
        :type do_update: bool
        :param do_finalize: If ``True``, this class' :meth:`finalize` 
            method is called after the event loop completes
        :type do_finalize: bool
        :param finalization_time: The amount of time for the remote process to
            serve data to a host after the Runtime's main() has completed
        :type finalization_time: float
        
        """      
        logger = logging.getLogger("acadia")

        # Prepare some variables that we'll use later
        current_time = datetime.now()
        self.remote_directory = current_time.strftime(remote_directory)
        self.local_directory = current_time.strftime(local_directory)
        self._username = username
        self._target_address = target_address
        self._remove_remote_directory = remove_remote_directory
        self._local_log_name = os.path.join(self.local_directory, "runtime.log")
        self._log_debug = log_debug
        self.login = f"{username}@{target_address}"
        self._displayed = False
        self._update_lock = Lock()
        self._update_lock_timeout = update_lock_timeout
        self._ssh_options = ["-i " + os.path.expanduser("~/.ssh/id_acadia"), "-o StrictHostKeyChecking=no"]

        # Create a local directory to save everything in before deployment
        os.makedirs(self.local_directory)

        # Set up logging
        log_level = logging.DEBUG if log_debug else logging.INFO
        
        while len(logger.handlers) > 0:
            h = logger.handlers[0]
            logger.removeHandler(h)
            h.close()

        handler = logging.FileHandler(self._local_log_name, mode="w")
        handler.setLevel(log_level)
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s'))
        logger.addHandler(handler)
        
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s'))
        logger.addHandler(handler)
        
        logger.setLevel(log_level)
        logger.propagate = False
        
        # Create a DataManager
        self.data_manager = DataManager()
        self.data_manager.add_group("properties", clear_before_sync=True, clear_after_send=False)
        self.data_manager["properties"].write({"time": current_time})
        self.data_manager.save(self.local_directory)
                
        self._configure_ssh(multiplex_control_path)
        self._prepare_files(files, runtime_module, log_level, finalization_time)
        self._prepare_screen()
        self._start_remote_runtime()
        self._create_event_loop(event_loop_period, do_initialize, do_update, do_finalize)

        self._set_status("Running")

    def stop(self, timeout=2) -> None:
        """
        Stop execution. This attempts to end the event loop, which will then
        attempt to stop the remote process.

        :param timeout: Time after which, if the event loop thread did not join,
            it is killed.
        """
        self._set_status("Requesting event loop stop")
        self._stop_flag.set()

        try: 
            # We don't need to remove the remote directory here since the 
            # event loop will do that for us when it's exiting
            self._event_loop.join(timeout=timeout)
            self._set_status("Stopped")
        except:
            logging.error("Event loop thread did not join, killing process")
            self.kill()
            if self._remove_remote_directory:
                self._set_status("Removing remote directory (after killing process)")
                run(f"ssh {' '.join(self._ssh_options)} {self.login} rm -r {self.remote_directory}".split(" "), check=True)

        if self._displayed:
            self._stop_button.disabled = True

    def kill(self) -> None:
        """
        Kill the remote process.
        """

        # Send a ctrl-C to the remote screen, if it exists
        run(f"ssh {' '.join(self._ssh_options)} {self.login} screen -S acadia -X stuff ^C".split(" "))
        self._set_status("Killed")

    def display(self) -> None:
        """
        Create a widget layout containing some useful controls.
        """
        from IPython.display import display
        from ipywidgets import Button, HTML, HBox, Label, Output
        
        # Create an overall grid for viewing plots and logs
        # grid = GridspecLayout()
        
        self.output = Output()
        with self.output:
            # Create a stop button
            def _self_stop(*args, **kwargs):
                self.stop()

            directory_label = Label(self.local_directory)
                
            self._stop_button = Button(
                description="Stop", 
                tooltip="Click to stop all local and remote processes.",
                button_style='danger')
            
            self._stop_button.on_click(_self_stop)
            self._status = HTML(value=f"")
            self._metadata_link = HTML(value=f"<a href=\"{os.path.join(self.local_directory, 'metadata.txt')}\">Metadata</a>")
            self._local_log_link = HTML(value=f"<a href=\"{self._local_log_name}\">Local Log</a>")
            self._remote_log_link = HTML(value=f"<a href=\"{os.path.join(self.local_directory, 'remote_main.log')}\">Remote Log</a>")
            box = HBox([directory_label, self._stop_button, self._status, self._metadata_link, self._local_log_link, self._remote_log_link])
        
        display(box, self.output)
        self._displayed = True

    @property
    def data(self) -> DataManager:
        return self.data_manager
    
    def is_done(self) -> bool:
        return self._event_loop is not None and not self._event_loop.is_alive()

    def savefig(self, figure, name: str = None) -> None:
        if name is None:
            idx = 0
            while os.path.exists(os.path.join(self.local_directory, f"fig{idx}.png")):
                idx += 1
            name = f"fig{idx}"
        # Pickle the figure for later use
        with open(os.path.join(self.local_directory, f"{name}.pkl"), "wb") as f:
            pickle.dump(figure, f)

        # Save an image file
        figure.canvas.close()
        image_filename = os.path.join(self.local_directory, f"{name}.png")
        figure.savefig(image_filename, dpi=500)
        
        # Replace the interactive canvas with a static image
        from IPython.display import Image, display
        display(Image(image_filename))
    
    # ----------------------- Internal utility functions --------------------- #

    @staticmethod
    def _transform_arg(v) -> Union[list, dict, str]:
        if isinstance(v, (bytes, bytearray)):
            return f"bytes;{hexlify(v).decode('ascii')}"
        
        if isinstance(v, np.ndarray):
            buf = BytesIO()
            write_array(buf, v)
            return f"ndarray;{hexlify(buf.getbuffer()).decode('ascii')}"
        
        if isinstance(v, (list, tuple)):
            return [Runtime._transform_arg(item) for item in v]
        
        if isinstance(v, dict):
            return {key: Runtime._transform_arg(value) for key,value in v.items()}
        
        if isinstance(v, complex):
            return f"complex;{v.real};{v.imag}"
        
        return v
    
    @staticmethod
    def _untransform_arg(v) -> Any:
        if isinstance(v, list):
            return [Runtime._untransform_arg(item) for item in v]
        
        if isinstance(v, dict):
            return {key: Runtime._untransform_arg(value) for key,value in v.items()}

        if isinstance(v, str) and v.startswith("bytes;"):
            return unhexlify(v[len("bytes;"):])
        
        if isinstance(v, str) and v.startswith("ndarray;"):
            buf = BytesIO(unhexlify(v[len("ndarray;"):]))
            return read_array(buf)
        
        if isinstance(v, str) and v.startswith("complex;"):
            _, real, imag = v.split(";")
            return complex(float(real), float(imag))
        
        return v
    
    def _configure_ssh(self, multiplex_control_path) -> None:
        # Configure SSH multiplexing
        self._set_status("Configuring SSH")

        if multiplex_control_path is None:
            self._multiplex_control_path = os.path.expanduser("~/.ssh/controlmasters")
        else:
            self._multiplex_control_path = multiplex_control_path

        if not os.path.exists(self._multiplex_control_path):
            os.mkdir(self._multiplex_control_path)

        # Create an SSH control master    
        run(f"ssh {' '.join(self._ssh_options)} -o ControlMaster=yes -o ControlPath={self._multiplex_control_path} -o ControlPersist=20 {self.login} exit", shell=True, stdout=PIPE, stderr=PIPE)
        self._ssh_options += [f"-o ControlMaster=auto", 
                                f"-o ControlPath={self._multiplex_control_path}/%r@%h:%p", 
                                f"-o ControlPersist=20"]
    
    def _get_fields(self) -> Dict[str,Any]:
        kwargs = {}
        for name,hint in get_type_hints(self.__class__).items():
            kwargs[name] = hint
        return kwargs

    def _dump_fields(self, fields: dict = None) -> None:
        logger = logging.getLogger("acadia")

        # Aggregate arguments by using introspection to retrieve the values
        # of all the class members that have annotations
        # This allows the user to specify relevant fields in the same way 
        # that one would for a dataclass
        logger.debug("Aggregating arguments")
        if fields is None:
            fields = {name: getattr(self, name) for name in self._get_fields().keys()}

        if len(fields) != 0:
            logger.debug(f"Saving arguments")
            filename = os.path.join(self.local_directory, "kwargs.json")
            with open(filename, "w") as f:
                json.dump(Runtime._transform_arg(fields), f, indent=4)
        else:
            logger.warning("No arguments found!")

    def _prepare_files(self, files, runtime_module, log_level, finalization_time) -> None:
        logger = logging.getLogger("acadia")
        self._set_status("Preparing and deploying files")

        # Copy all of the files that we need into the local execution directory
        if files is not None:
            for file in files:
                if isinstance(file, str):
                    src = file
                    dst = os.path.join(self.local_directory, os.path.basename(file))
                elif isinstance(file, tuple):
                    src = file[0]
                    dst = os.path.join(self.local_directory, file[1])
                else:
                    raise TypeError(f"Unable to prepare file: {file}")
                
                shutil.copyfile(src, dst)

        # Create the run file
        with open(os.path.join(self.local_directory, "run.py"), "w") as runfile:
            runfile.write(f"import traceback\n")
            runfile.write(f"import sys\n")
            runfile.write(f"import time\n")
            runfile.write(f"sys.stdout = open(\"{self.remote_directory}/remote_stdout.log\", 'w')\n")
            runfile.write(f"sys.stderr = open(\"{self.remote_directory}/remote_stderr.log\", 'w')\n\n")

            runfile.write(f"import logging\n")
            runfile.write(f"logging.basicConfig("
                          f"level={log_level},"
                          f" filename='{os.path.join(self.remote_directory, 'remote_main.log')}',"
                          f" filemode='w',"
                          f" format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')\n\n")
            
            runfile.write(f"try:\n")
            runfile.write(f"    import os\n")
            runfile.write(f"    os.chdir(\"{self.remote_directory}\")\n")
            runfile.write(f"    from {runtime_module if runtime_module is not None else self.__module__} import {self.__class__.__qualname__}\n")
            runfile.write(f"    runtime = {self.__class__.__qualname__}.load(\"{self.remote_directory}\")\n")
            runfile.write(f"    runtime.data.serve()\n")
            runfile.write(f"    logging.info(\"Executing main()...\")\n")
            runfile.write(f"    runtime.main()\n")            
            runfile.write(f"    logging.info(\"Runtime complete.\")\n")
            runfile.write(f"except:\n")
            runfile.write(f"    logging.error(f'Runtime exception:\\n{{traceback.format_exc()}}')\n\n")
            runfile.write(f"sys.stdout.flush()\n")
            runfile.write(f"sys.stderr.flush()\n")
            runfile.write(f"exit(0)\n")

        self._dump_fields()

        # Deploy everything
        cmd = f"rsync -r --mkpath -e \"ssh {' '.join(self._ssh_options)}\" {self.local_directory}/ {self.login}:{self.remote_directory}/"
        # import pdb; pdb.set_trace()
        # cmd = f"scp -r {self.local_directory} {self.login}:{self.remote_directory}"
        logger.debug(f"Executing command {cmd}")
        r = run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)

    def final_serve(self, timeout=5) -> None:
        """
        Finalize the internal DataManager and spin the data server for a given amount of time to allow a remote host to
        retrieve data. If no client is connected, if data is sent, or if the client
        requests a hangup, the loop will exit.
        """
        self.data.finalize()

        import time
        tstart = time.time()
        retval = None
        while time.time() - tstart < timeout:
            # Only exit the serve loop if the client told us to
            retval = self.data.serve()
            if retval == DataManager.serve_hangup():
                break
            
        logging.debug(f"DataManager serve loop finished with retval {retval}.")
        self.data.disconnect()
    
    def _list_remote_screens() -> tuple[str,str]:
        cmd = f"ssh {' '.join(self._ssh_options)} {self.login} screen -ls | grep -E --only-matching \"[0-9]+\\.[a-z0-9 -\\.]+\""
        r = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        return [s for s in r.stdout.decode("utf-8").split("\n") if s != '']

    def _prepare_screen() -> str:
        """
        Retrieve a preprepared runtime screen, if it exists.
        """
        logger = logging.getLogger("acadia")
        self._set_status("Preparing remote runtime screen")

        cmd = ""

        # If there's already an existing acadia screen running, we'll need to kill it
        screen_found = False
        for s in self._list_remote_screens():
            if s.endswith("acadia"):
                logger.warning(f"Killing remote screen {s}")
                cmd += f"screen -S {s} -X kill; "
            elif s.endswith("acadia-prep"):
                # Acquire and rename the existing screen
                cmd += f"screen -S {s} -X sessionname acadia; "
                screen_found = True

        if not screen_found:
            # Create an acadia screen to use now
            cmd += "screen -dmS acadia python3; "
            cmd += "screen -S acadia -X stuff \"from acadia import *; import numpy;^M\"; "

        # Prepare a screen for next time
        cmd += "screen -dmS acadia-prep python3; "
        cmd += "screen -S acadia-prep -X stuff \"from acadia import *; import numpy;^M\"; "

        cmd = f"ssh {' '.join(self._ssh_options)} {self.login} {cmd}"
        logger.debug(f"Executing command {cmd}")
        run(cmd.split(" "), stdout=PIPE)

    def _start_remote_runtime(self) -> None:
        self._set_status("Starting remote runtime")
        cmd = f"ssh {' '.join(self._ssh_options)} {self.login} \"screen -S acadia -X readreg p {self.remote_directory}/run.py; screen -S acadia -X paste p\""
        run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)

    def _retrieve_logs(self) -> None:
        cmd = f"rsync -e \"ssh {' '.join(self._ssh_options)}\" --append {self.login}:{self.remote_directory}/*.log {self.local_directory}"
        logging.getLogger("acadia").debug(f"Retrieving logs with command: {cmd}")
        proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            raise ValueError(f"Process returned non-zero exit code:\n{proc}")
    
    def _create_event_loop(self, 
                           event_loop_period: float, 
                           do_initialize: bool, 
                           do_update: bool, 
                           do_finalize: bool) -> None:
        self._stop_flag = Event()

        def event_loop():
            import time

            if do_initialize:
                self._set_status("Initializing event loop")
                self.initialize()

            self._set_status("Event loop running")

            t_loop = time.time()
            logger = logging.getLogger("acadia")

            while True:
                if self._stop_flag.is_set():
                    logger.debug("Stop requested")
                    break
                
                logger.debug("Checking runtime for completion")

                try:
                    screens = self._list_remote_screens()
                    found = False
                    for s in screens:
                        if s.endswith("acadia"):
                            logger.debug(f"Identified acadia screen as {s}")
                            found = True
                            break

                    if not found:
                        logger.info("Acadia screen not present, indicating completion")
                        break
                except:
                    logger.error(f"Exception checking for screens: {traceback.format_exc()}")
                
                # Synchronize with the target and perform any updates
                if not self.data.is_connected():
                    logger.debug("Connecting to remote target DataManager")
                    try: 
                        self.data.connect(self._target_address)
                        logger.debug("Connected")
                    except ConnectionRefusedError:
                        logger.warning("Unable to connect to target DataManager")
                    except:
                        logger.error(f"Exception connecting to DataManager: {traceback.format_exc()}")

                if self.data.is_connected():
                    result = self._update_lock.acquire(timeout=self._update_lock_timeout)
                    if result:
                        try:
                            logger.debug("Syncing")
                            self.data.sync(timeout_ms=5000)
                            logger.debug("Synced")
                        except:
                            logger.error(f"Exception synchronizing: {traceback.format_exc()}")

                        if do_update:
                            try:
                                logger.debug("Updating...")
                                self.update()
                                logger.debug("Update complete")
                            except:
                                logger.error(f"Exception updating: {traceback.format_exc()}")        
                                
                        self._update_lock.release()

                        if self.data.is_finalized():
                            logger.info("Received fully finalized data; exiting event loop")
                            break
                    else:
                        logger.warning("Unable to acquire update lock")

                self._retrieve_logs()

                # Ensure that at least event_loop_period seconds have passed
                while time.time() < t_loop + event_loop_period:
                    pass

                t_loop = time.time()

            if do_finalize:
                self._set_status("Finalizing event loop")
                result = self._update_lock.acquire(timeout=self._update_lock_timeout)
                if result:
                    try:
                        self.update()
                        self.finalize()
                        logger.debug("Update complete")
                    except:
                        logger.error(f"Exception during finalization: {traceback.format_exc()}")
                        
                    self._update_lock.release()
                else:
                    logger.error("Unable to acquire update lock, finalization incomplete")

            try:
                self.data.hangup()
            except:
                logger.error("Failed to hang up remote DataManager")
            
            try:
                self._retrieve_logs()
            except:
                logger.error("Failed to receive logs from remote")

            if self._displayed:
                self._stop_button.disabled = True

            if self._remove_remote_directory:
                try:
                    self._set_status("Removing remote directory")
                    run(f"ssh {' '.join(self._ssh_options)} {self.login} rm -r {self.remote_directory}".split(" "), check=True)
                except:
                    logger.error("Failed to remove remote directory")
                    
            self._set_status("Completed")
            
        self._event_loop = Thread(target=event_loop,
                        name="EventLoopThread",
                        daemon=True)
        self._set_status("Starting event loop")
        self._event_loop.start()

    def _set_status(self, status):
        logger = logging.getLogger("acadia")
        s = f"Status: {status}"
        if self._displayed:
            self._status.value = s
        logger.debug(s)
        
        