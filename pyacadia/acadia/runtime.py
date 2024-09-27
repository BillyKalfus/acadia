import os
import traceback
import logging
import json
import shutil

from datetime import datetime
from threading import Thread, Event
from typing import Any
from dataclasses import asdict, is_dataclass
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
            runtime_class: str,
            files: list[str] = None,
            remote_directory: str = "/tmp/%y%m%d_%H%M%S", 
            local_directory: str = "/tmp/%y%m%d_%H%M%S",
            username: str = "root", 
            log_debug: bool = False,
            event_loop_period: float = 0.25,
            remove_remote_directory: bool = True,
            multiplex_control_path: str = None,
            do_initialize: bool = True,
            do_update: bool = True,
            do_finalize: bool = True,
            finalization_time: float = 10,
            **kwargs):
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
        safely deleted (and will be done so automatically if 
        ``remove_remote_directory=True``).
        
        Deployment is carried out using SSH and a password prompt is not 
        implemented, meaning that key-based authentication must be configured
        on the target prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done when the target does not
        already contain a copy of the host's key, such as when the target
        is used for the first time or when the target's key storage is reset
        (for Acadia hardware, this occurs when the system is power cycled). 
        :param target_address: IP address of the target
        :type target_address: str
        :param runtime_class: Name of the :class:`Runtime` subclass This is 
            directly used in an ``import``
            statement as ``import <runtime_class> as ...``.
        :type runtime_class: str
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

        # Create a local directory to save everything in before deployment
        os.makedirs(self.local_directory)

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
                
        self._set_status("Configuring SSH multiplexing")
        self._configure_ssh(multiplex_control_path)

        self._set_status("Preparing and deploying files")
        self._prepare_files(files, runtime_class, log_level, finalization_time, kwargs)

        self._set_status("Preparing remote runtime screen")
        Runtime._prepare_screen(self.login, self._multiplex_options)

        self._set_status("Starting remote runtime")
        cmd = f"ssh {self._multiplex_options} {self.login} \"screen -S acadia -X readreg p {self.remote_directory}/run.py; screen -S acadia -X paste p\""
        run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
        
        self._stop_flag = Event()
        
        self._set_status("Starting event loop")
        self._event_loop = self._create_event_loop(event_loop_period, do_initialize, do_update, do_finalize)
        self._event_loop.start()

        self._set_status("Running")

    def stop(self, timeout=2):
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
            logging.error("Event loop thread did not join, manually stopping")
            self.kill()
            if self._remove_remote_directory:
                self._set_status("Removing remote directory (after killing process)")
                run(f"ssh {self._multiplex_options} {self.login} rm -r {self.remote_directory}".split(" "), check=True)

        if self._displayed:
            self._stop_button.disabled = True

    def kill(self):
        """
        Kill the remote process.
        """

        # Send a ctrl-C to the remote screen, if it exists
        run(f"ssh {self._multiplex_options} {self.login} screen -S acadia -X stuff ^C".split(" "))
        self._set_status("Killed")

    def display(self):
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
                tooltip="Click to stop all local and remote processes.")
            
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
    
    def is_done(self):
        return self._event_loop is not None and not self._event_loop.is_alive()
    
    # ----------------------- Internal utility functions --------------------- #

    @staticmethod
    def _transform_arg(v):
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
        
        return v
    
    @staticmethod
    def _untransform_arg(v):
        if isinstance(v, list):
            return [Runtime._untransform_arg(item) for item in v]
        
        if isinstance(v, dict):
            return {key: Runtime._untransform_arg(value) for key,value in v.items()}

        if isinstance(v, str) and v.startswith("bytes;"):
            return unhexlify(v[len("bytes;"):])
        
        if isinstance(v, str) and v.startswith("ndarray;"):
            buf = BytesIO(unhexlify(v[len("ndarray;"):]))
            return read_array(buf)
        
        return v
    
    def _configure_ssh(self, multiplex_control_path):
        # Configure SSH multiplexing
        if multiplex_control_path is None:
            self._multiplex_control_path = os.path.expanduser("~/.ssh/controlmasters")
        else:
            self._multiplex_control_path = multiplex_control_path

        if not os.path.exists(self._multiplex_control_path):
            os.mkdir(self._multiplex_control_path)

        # Create an SSH control master    
        # run(f"ssh -o ControlMaster=yes -o ControlPath={self._multiplex_control_path} -o ControlPersist=20 {self.login} exit", shell=True, stdout=PIPE, stderr=PIPE)
        self._multiplex_options = (f"-o ControlMaster=auto -o ControlPath={self._multiplex_control_path}/%r@%h:%p -o ControlPersist=20")
    
    def _prepare_files(self, files, runtime_filename, log_level, finalization_time, kwargs):
        logger = logging.getLogger("acadia")

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
            runfile.write(f"    from {runtime_filename} import {self.__class__.__qualname__}\n")
            runfile.write(f"    runtime = {self.__class__.__qualname__}.load(\"{self.remote_directory}\")\n")
            runfile.write(f"    runtime.data.serve()\n")
            runfile.write(f"    logging.info(\"Executing main()...\")\n")
            runfile.write(f"    runtime.main()\n")
            runfile.write(f"    logging.info(\"main() complete, spinning server for {finalization_time} seconds\")\n")
            runfile.write(f"    runtime.data.finalize()\n")
            runfile.write(f"    tstart = time.time()\n")
            runfile.write(f"    retval = 2\n")
            runfile.write(f"    while retval != 3 and time.time()-tstart < {finalization_time}:\n")
            runfile.write(f"        retval = runtime.data.serve()\n")
            runfile.write(f"    if retval == 1:\n")
            runfile.write(f"        logging.warning(\"DataManager not connected to client.\")\n")
            runfile.write(f"    if retval == 2:\n")
            runfile.write(f"        logging.warning(\"DataManager failed to serve data to client during finalization.\")\n")
            runfile.write(f"    logging.debug(f\"DataManager serve loop finished with retval {{retval}}.\")\n")
            runfile.write(f"    logging.info(\"Runtime complete.\")\n")
            runfile.write(f"    runtime.data.disconnect()\n")
            runfile.write(f"except:\n")
            runfile.write(f"    logging.error(f'Runtime exception:\\n{{traceback.format_exc()}}')\n\n")
            runfile.write(f"sys.stdout.flush()\n")
            runfile.write(f"sys.stderr.flush()\n")
            runfile.write(f"exit(0)\n")

        logger.debug("Aggregating arguments")
        if is_dataclass(self):
            kwargs.update(asdict(self))
        if hasattr(self, "__getstate__"):
            tmp = self.__getstate__()
            if not isinstance(tmp, dict):
                raise TypeError("Runtime objects that implement `__getstate__` must"
                                f" return a dict (received {type(tmp)})")
            kwargs.update(tmp)

        if len(kwargs) != 0:
            logger.debug(f"Saving arguments")
            filename = os.path.join(self.local_directory, "kwargs.json")
            with open(filename, "w") as f:
                json.dump(Runtime._transform_arg(kwargs), f, indent=4)
        else:
            logger.warning("No arguments found!")

        # Deploy everything
        cmd = f"rsync -r --mkpath -e \"ssh {self._multiplex_options}\" {self.local_directory}/ {self.login}:{self.remote_directory}/"
        logger.debug(f"Executing command {cmd}")
        run(cmd, shell=True, check=True)
    
    @staticmethod
    def _list_remote_screens(login, multiplex_options) -> tuple[str,str]:
        cmd = f'ssh {multiplex_options} {login} screen -ls | grep -E --only-matching "[0-9]+\.[a-z0-9 -\.]+"'
        r = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        return [s for s in r.stdout.decode("utf-8").split("\n") if s != '']

    @staticmethod
    def _prepare_screen(login, multiplex_options) -> str:
        """
        Retrieve a preprepared runtime screen, if it exists.
        """
        logger = logging.getLogger("acadia")

        cmd = ""

        # If there's already an existing acadia screen running, we'll need to kill it
        screen_found = False
        for s in Runtime._list_remote_screens(login, multiplex_options):
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
            cmd += "screen -S acadia -X stuff \"import acadia.system; import acadia.sequencer; import numpy;^M\"; "

        # Prepare a screen for next time
        cmd += "screen -dmS acadia-prep python3; "
        cmd += "screen -S acadia-prep -X stuff \"import acadia.system; import acadia.sequencer; import numpy;^M\"; "

        cmd = f"ssh {multiplex_options} {login} {cmd}"
        logger.debug(f"Executing command {cmd}")
        run(cmd.split(" "), stdout=PIPE)

    def _retrieve_logs(self):
        cmd = f"rsync -e \"ssh {self._multiplex_options}\" --append {self.login}:{self.remote_directory}/*.log {self.local_directory}"
        logging.getLogger("acadia").debug(f"Retrieving logs with command: {cmd}")
        proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            raise ValueError(f"Process returned non-zero exit code:\n{proc}")
    
    def _create_event_loop(self, 
                           event_loop_period: float, 
                           do_initialize: bool, 
                           do_update: bool, 
                           do_finalize: bool) -> Thread:
                
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
                    screens = Runtime._list_remote_screens(self.login, self._multiplex_options)
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
                try:
                    if not self.data.is_connected():
                        logger.debug("Connecting to remote target DataManager")
                        self.data.connect(self._target_address)
                        logger.debug("Connected")

                    # Exception will be thrown above if we're not connected and we can't connect
                    logger.debug("Syncing")
                    self.data.sync()
                    logger.debug("Synced")

                    if do_update:
                        logger.debug("Updating...")
                        self.update()
                        logger.debug("Update complete")

                    if self.data.is_finalized():
                        logger.info("Received fully finalized data; exiting event loop")
                        self.data.hangup()
                        break
                except ConnectionRefusedError:
                    logger.warning("Unable to connect to target DataManager")
                except:
                    logger.error(f"Exception synchronizing: {traceback.format_exc()}")

                self._retrieve_logs()

                # Ensure that at least event_loop_period seconds have 
                while time.time() < t_loop + event_loop_period:
                    pass

                t_loop = time.time()

            if do_finalize:
                self._set_status("Finalizing event loop")
                try:
                    self.update()
                    self.finalize()
                except:
                    logger.error(f"Exception during finalization: {traceback.format_exc()}")

            self._retrieve_logs()

            if self._displayed:
                self._stop_button.disabled = True

            if self._remove_remote_directory:
                self._set_status("Removing remote directory")
                run(f"ssh {self._multiplex_options} {self.login} rm -r {self.remote_directory}".split(" "), check=True)

            self._set_status("Completed")
            
        thread = Thread(target=event_loop,
                        name="EventLoopThread",
                        daemon=True)
        return thread

    def _set_status(self, status):
        logger = logging.getLogger("acadia")
        s = f"Status: {status}"
        if self._displayed:
            self._status.value = s
        logger.debug(s)
        
        