import os
import traceback
import logging
import pickle
import shutil

from datetime import datetime, timezone
from threading import Thread, Event
from typing import Tuple, Any, Union
from dataclasses import asdict, is_dataclass
from subprocess import Popen, PIPE, run, CompletedProcess, CalledProcessError

from .data import DataManager

__all__ = ["Runtime"]

logger = logging.getLogger()

class Runtime:
    """
    An orchestrated deployment of a program on a remote target.

    Subclasses of :class:`Runtime` are expected to be created for each workflow
    a user may want. The :meth:`deploy` method allows a host machine (the one 
    that the user is actively logged into and using as an interface to the
    instrumentation) to remotely deploy a procedure on a remote machine, as 
    specified by the subclass' implementation of :meth:`main`. Meanwhile, on the
    host, a custom event loop runs in a background thread for monitoring the
    remote process' status and retrieving data files. The user may add callbacks
    """
    
    # ---------------- Functions to be implemented or overridden by the user ------------- #
    def main(self, directory: str, datamanager: DataManager) -> Any:
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
    def deploy(self, 
            target_address: str, 
            runtime_module: str,
            files: list[str] = None,
            remote_base_directory: str = "/run/media/mmcblk0p1", 
            local_base_directory: str = "/tmp",
            subdirectory_name: str = None,
            time_format: str = "%m%d%y-%H%M%S",
            username: str = "root", 
            log_level=logging.INFO,
            update_period: float = 0.2,
            remove_remote_directory: bool = True,
            multiplex_control_path: str = None,
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
        :param runtime_module: Module containing the class definition of the
            :class:`Runtime` to execute. This is directly used in an ``import``
            statement as ``from <runtime_module> import <subclass_name>``, and
            the subclass name is automatically extracted when this method is 
            called.
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
        :param remote_base_directory: Base directory on the target within which
            the execution directory is stored.
        :type remote_base_directory: str
        :param local_base_directory: Base directory on the host within which 
            the execution directory is stored.
        :type local_base_directory: str

  
        """      
        # Prepare some variables that we'll use later
        time_str = datetime.now(timezone.utc).strftime(time_format)
        subdirectory = subdirectory_name if subdirectory_name is not None else time_str
        self.remote_directory = os.path.join(remote_base_directory, subdirectory)
        self.local_directory = os.path.join(local_base_directory, subdirectory)
        self._username = username
        self._target_address = target_address
        self._remove_remote_directory = remove_remote_directory
        self._local_log_name = os.path.join(self.local_directory, "runtime.log")
        self._log_level = log_level
        self.login = f"{username}@{target_address}"

        # Create a local directory to save everything in before deployment
        os.mkdir(self.local_directory)
        
        logging.basicConfig(level=log_level, 
                    filename=self._local_log_name, 
                    filemode="w",
                    format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')
                
        self._set_status("Configuring SSH multiplexing")
        self._configure_ssh(multiplex_control_path)

        self._set_status("Preparing and deploying files")
        self._prepare_files(files, runtime_module, remote_base_directory, log_level, kwargs)

        self._set_status("Preparing remote runtime screen")
        Runtime._prepare_screen(self.login, self._multiplex_options)

        self._set_status("Starting remote runtime")
        cmd = f"ssh {self._multiplex_options} {self.login} \"screen -S acadia -X readreg p {self.remote_directory}/run.py; screen -S acadia -X paste p\""
        run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
        
        self._stop_flag = Event()
        self.local_data_manager = DataManager(self.local_directory)
        
        self._set_status("Starting event loop")
        self._event_loop = self._create_event_loop(update_period)
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
            self._event_loop.join(timeout=timeout)
        except:
            logging.error("Event loop thread did not join, manually stopping")
            self.kill()

        self._set_status("Stopped")

    def kill(self):
        """
        Kill the remote process.
        """

        # Send a ctrl-C to the remote screen, if it exists
        run(f"ssh {self._multiplex_options} {self.login} screen -S acadia -X stuff ^C".split(" "))
        
        self._stop_button.disabled = True

        if self._remove_remote_directory:
            self._set_status("Removing remote directory")
            run(f"ssh {self._multiplex_options} {self.login} rm -r {self.remote_directory}".split(" "), check=True)

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
            self._metadata_link = HTML(value=f"<a href=\"{os.path.join(self.local_directory, 'metadata.json')}\">Metadata</a>")
            self._local_log_link = HTML(value=f"<a href=\"{self._local_log_name}\">Local Log</a>")
            self._remote_log_link = HTML(value=f"<a href=\"{os.path.join(self.local_directory, 'remote_main.log')}\">Remote Log</a>")
            box = HBox([directory_label, self._stop_button, self._status, self._metadata_link, self._local_log_link, self._remote_log_link])
        
        
        display(box, self.output)

    @property
    def data(self):
        return self.local_data_manager
    
    # ----------------------- Internal utility functions --------------------- #

    def _save_args(self, directory: str, **kwargs) -> str:
        """
        Save all necessary arguments into a file in the given directory.
        """
        filename = os.path.join(directory, "kwargs.pkl")
        with open(filename, "wb") as f:
            pickle.dump(kwargs, f)
        
        return filename

    @staticmethod
    def _load_args(directory: str) -> dict:
        """
        Load saved arguments. 
        """
        path = os.path.join(directory, "kwargs.pkl")
        if not os.path.exists(path):
            return {}
        
        with open(path, "rb") as f:
            data = pickle.load(f)
            
        return data
    
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
    
    def _prepare_files(self, files, runtime_module, remote_base_directory, log_level, kwargs):
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
                
                shutil.copy2(src, dst)

        # Create the run file
        with open(os.path.join(self.local_directory, "run.py"), "w") as runfile:
            runfile.write(f"import traceback\n")
            runfile.write(f"import sys\n")
            runfile.write(f"sys.stdout = open(\"{self.remote_directory}/stdout.log\", 'w')\n")
            runfile.write(f"sys.stderr = open(\"{self.remote_directory}/stderr.log\", 'w')\n\n")

            runfile.write(f"import logging\n")
            runfile.write(f"logging.basicConfig("
                          f"level={log_level},"
                          f" filename='{os.path.join(self.remote_directory, 'remote_main.log')}',"
                          f" filemode='w',"
                          f" format='[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s')\n\n")
            
            runfile.write(f"try:\n")
            runfile.write(f"    import os\n")
            runfile.write(f"    os.chdir(\"{self.remote_directory}\")\n")
            runfile.write(f"    from acadia.runtime import Runtime\n")
            runfile.write(f"    from {runtime_module} import {self.__class__.__name__}\n")
            runfile.write(f"    kwargs = Runtime._load_args(\"{self.remote_directory}\")\n")
            runfile.write(f"    runtime = {self.__class__.__name__}(**kwargs)\n")
            runfile.write(f"    runtime.run(\"{self.remote_directory}\", {log_level})\n")
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
            self._save_args(self.local_directory, **kwargs)
        else:
            logger.warning("No arguments found!")

        # Deploy everything
        cmd = f"rsync -r -e \"ssh {self._multiplex_options}\" {self.local_directory} {self.login}:{remote_base_directory}"
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

    def _update_files(self, last_update: str = None):
        """
        Sync local files with those on the target
        """
        # Get logs
        cmd = f"rsync -e \"ssh {self._multiplex_options}\" --append {self.login}:{self.remote_directory}/*.log {self.local_directory}"
        proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            raise ValueError(f"Process returned non-zero exit code:\n{proc}")

        # Check to see whether any data has updated
        cmd = f"ssh {self._multiplex_options} {self.login} stat --format \"%Y\" {self.remote_directory}/metadata.json"
        modification_time = run(cmd.split(" "), stdout=PIPE, stderr=PIPE)

        if modification_time == last_update:
            logging.debug("No update since last check")
            return modification_time
        
        logging.debug("Update available")

        # Lock the metadata, only to be unlocked once we've grabbed it
        # Do this by creating a process that locks metadata and runs a loop that blocks until a file exists
        # then we'll create that file once we're done and the loop will exit
        unlock_file = f"{self.remote_directory}/metadata.unlock"
        lock_cmd = f"ssh {self._multiplex_options} {self.login} flock {self.remote_directory}/metadata.json -c \"while [ ! -f {unlock_file} ]; do sleep 0.000001; done; rm {unlock_file}\""
        lock_proc = Popen(lock_cmd.split(" "), stdout=PIPE, stderr=PIPE)    

        # Now actually pull the file itself
        cmd = f"rsync -e \"ssh {self._multiplex_options}\" --inplace {self.login}:{self.remote_directory}/metadata.json {self.local_directory}/metadata.json"
        proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            raise ValueError(f"Process returned non-zero exit code:\n{proc}")

        # Unlock the metadata by creating the unlock file
        cmd = f"ssh {self._multiplex_options} {self.login} touch {unlock_file}"
        proc = run(cmd.split(" "), stdout=PIPE, stderr=PIPE)
        if proc.returncode != 0:
            raise ValueError(f"Process returned non-zero exit code:\n{proc}")
        
        # Verify that the lock process actually ended properly
        # if not isinstance(lock_proc, CompletedProcess):
        #     raise TypeError("Metadata lock process did not terminate.")

        # Get data files
        # TODO: we're not checking errors in this command because it'll error when there
        # are no bin files in the remote directory, but we'd still like to catch unexpected
        # problems
        cmd = f"rsync -e \"ssh {self._multiplex_options}\" --append {self.login}:{self.remote_directory}/*.bin {self.local_directory}"
        proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        # if proc.returncode != 0:
        #     raise ValueError(f"Process returned non-zero exit code:\n{proc}")

        # Reload the data manager and call any subclass update routines
        self.local_data_manager.load(reload=True)
        logging.debug("Data retrieval complete, calling `update`")

        self.update()
        logging.debug("Update complete")

        return modification_time
    
    def _create_event_loop(self, update_period: float) -> Thread:
                
        def _func():
            import time

            self._set_status("Initializing event loop")
            self.initialize()

            self._set_status("Event loop running")

            t_loop = time.time()
            last_update_time = None
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
                
                # Update any processing
                try:
                    last_update_time = self._update_files(last_update_time)
                except:
                    logger.error(f"Exception updating: {traceback.format_exc()}")

                # Ensure that at least update_period seconds have 
                while time.time() < t_loop + update_period:
                    pass

                t_loop = time.time()

            self._set_status("Performing final update")
            try:
                self._update_files(last_update_time)
            except:
                logger.error(f"Exception updating: {traceback.format_exc()}")

            self._set_status("Finalizing event loop")
            try:
                self.finalize()
            except:
                logger.error(f"Exception during finalization: {traceback.format_exc()}")

            self._set_status("Completed")
            
        thread = Thread(target=_func,
                        name="EventLoopThread",
                        daemon=True)
        return thread

    def _set_status(self, status):
        s = f"Status: {status}"
        if hasattr(self, "_status"):
            self._status.value = s
        logger.debug(s)
        
    # ----------------- Function that is run on the target ----------------- #

    def run(self, directory, log_level=logging.INFO):
        """
        This is the main entry point of the remote process. This should not 
        be called manually unless executed on the target itself.
        """
        import os
        from acadia.data import DataManager
        import logging

        logger = logging.getLogger()

        if not os.path.exists(directory):
            logger.info(f"Creating output directory {directory}")
            try:
                os.mkdir(directory)
            except:
                logger.error(f"Exception creating output directory {directory}:"
                            f" {traceback.format_exc()}")
            
        os.chdir(directory)

        logger.debug(f"Creating DataManager")
        mgr = DataManager(directory=directory)

        logger.info("Running main method")
        try:
            self.main(directory, mgr)
        except:
            logger.error(f"Exception in `main`: {traceback.format_exc()}")

        logger.info("Main complete, saving")
        mgr.save()
        logger.info("Saved")
        