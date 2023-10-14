import os
import traceback
import subprocess
from threading import Thread, Event
from functools import partial
from abc import ABC, abstractclassmethod

__all__ = ["Runtime"]

class Runtime(ABC):
    """
    An organization class for orchestrating the deployment of programs on 
    remote targets.
    """
    
    def __init__(self, 
                 target_ip, 
                 filename,
                 target_port=6672, 
                 jump_server=None, 
                 update_period=0.1):
        self._target_ip = target_ip
        self._target_port = target_port
        self._jump_server = jump_server
        self._update_thread = None
        self._update_period = update_period
        self._proc = None
        self._filename = filename
        
    def run(self):
        """
        Deploy the procedure implemented by :meth:`remote_main` on a remote
        target. Note that key-based authentication MUST be configured on the 
        target prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done once.  
  
        :param block: If `True`, this method will block until the 
            :class:`DataManager` running on the target provides a progress
            update indicating that all iterations have completed. Otherwise,
            the method will return after starting all required threads without
            waiting.
        :type block: bool
        """ 
        # Deploy a process on the target that will call main()
        import logging
        
        logging.info(f"Deploying runtime file {self._filename}...")
        
        # Copy over the subclass file
        subprocess.run(['scp', 
                        f'{self._filename}', 
                        f'root@{self._target_ip}:/home/root'], 
                       check=True, 
                       capture_output=True)
        
        args = ["ssh", "-t", "-t"]
        
        if self._jump_server is not None:
            args += ["-J", self._jump_server]
            
        cls = self.__class__.__name__
        python_cmd = (f"python3 -c \""
                      f"import logging; "
                      f"logging.basicConfig("
                        f"filename=\\\"/home/root/{os.path.basename(self._filename)}.log\\\","
                        f" format=\\\"[%(asctime)s] %(levelname)s at %(funcName)s (%(filename)s, %(lineno)d): %(message)s\\\","
                        f" level=logging.DEBUG,"
                        f" filemode=\\\"w\\\"); "
                      f"f = open(\\\"/home/root/{os.path.basename(self._filename)}\\\", \\\"rb\\\"); "
                      f"exec(f.read()); "
                      f"f.close(); "
                      f"{cls}.remote_main()\"")
        
        logging.info("Running remote process...")
        logging.debug(f"Deploying python command {python_cmd}")
        
        args += [f"root@{self._target_ip}", f"bash -c '{python_cmd}'"]
        self._proc = subprocess.Popen(args, 
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, 
                                      stderr=subprocess.PIPE,
                                      preexec_fn=os.setsid)
        
        # Create an event for signalling threads to stop
        self._stop_event = Event()
        
        fig, init_func, update_func = self.plot()
        
        # Create a generator that will allow us to monitor the progress of the
        # remote process
        progress_gen = partial(Runtime._progress_generator, 
                               stop_event=self._stop_event, 
                               address=(self._target_ip, self._target_port))
        
        # Create a new thread for keeping track of progress and rendering
        def thread_func():
            if (fig is not None 
                    and init_func is not None 
                    and update_func is not None):            
                # If we're making a plot, create an animation that will consume the progress
                # generator at the desired rate
                from matplotlib.animation import FuncAnimation  
                update_func_with_address = partial(update_func, (self._target_ip, self._target_port))
                self._anim = FuncAnimation(fig, 
                            func=update_func_with_address, 
                            init_func=init_func,
                            frames=progress_gen, 
                            repeat=False, 
                            blit=True,
                            interval=self._update_period)
            else:
                # No plot, just consume the iterable
                import time
                for progress_dict in progress_gen():
                    logging.info(f"Received progress {progress_dict}")
                    time.sleep(self._update_period)
                
                
        self._update_thread = Thread(target=thread_func, name="UpdateThread", daemon=True)
        self._update_thread.start()
        
    def stop(self):
        """
        Gracefully stop any running process.
        """
        if self._proc is None:
            # We never started
            return
        
        # Stop the update thread that we may have started
        self._stop_event.set()
        self._update_thread.join()
        
        # Request the data manager server to stop
        from acadia.data import DataManager
        DataManager.stop_remote_server((self._target_ip, self._target_port))
        
        if self._proc.poll() is None:
            # The process is still running, kill it
            self._proc.kill()

    @classmethod
    def remote_main(cls):
        """
        This is the main entry point of the remote process. This should not 
        be called manually.
        """
        import time
        import logging
        from acadia.data import DataManager
        
        mgr = DataManager("/home/root")
        mgr.start_server()
        
        # Wait for the server to start without spamming it
        tries = 100
        while not mgr.server_running() and tries > 0:
            time.sleep(0.01)
            tries -= 1
            
        if not mgr.server_running():
            raise ValueError("Unable to start server.")
        
        # Run the user main program
        try:
            cls.main(mgr)
        except:
            logging.debug(f"Exception raised in main():\n{traceback.format_exc()}")
        
        # Mark the progress as complete so that the client sees it
        mgr.save()
        mgr.progress_complete()
        
        # Give the client a bit of time to get the last data and stop the 
        # server; otherwise kill it ourselves
        
        tries = 100
        while mgr.server_running() and tries > 0:
            time.sleep(0.01)
            tries -= 1
        mgr.stop_server()
        
    @abstractclassmethod
    def main(cls, data_manager):
        """
        A function that will be run on the target upon deployment. A newly-
        initialized :class:`DataManager` is passed as the only argument to
        this method.
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
    
    @staticmethod
    def _progress_generator(stop_event, address, timeout=10):
        """
        A generator for tracking the progress of the remote process.
        """
        # Repeatedly ask for progress until we get a valid progress 
        # dictionary from the server
        import time
        import logging
        from tqdm.notebook import tqdm
        from acadia.data import DataManager
        
        
        logging.debug("Progress generator created")
        
        progress_dict = {}
        bar = None
        tstart = time.time()
        while len(progress_dict) == 0:
            if stop_event.is_set():
                logging.debug("Stopping progress generator")
                return
            
            if time.time() - tstart > timeout:
                logging.debug("Progress generator timed out waiting for first report")
                return
            
            rcvd = DataManager.receive_counters(address)
            
            if rcvd is not None:
                progress_dict = rcvd
                
            yield progress_dict
            
        logging.debug(f"Received first valid progress {progress_dict}")
                
        if "total" in progress_dict: 
            logging.debug(f"Creating progress bar with state {rcvd}")              
            bar = tqdm(total=progress_dict["total"])
            bar.update(progress_dict["progress"])
            
        while not progress_dict["complete"]:
            if stop_event.is_set():
                logging.debug("Stopping progress generator")
                break
            rcvd = DataManager.receive_counters(address)
            if rcvd is not None and len(rcvd) > 0:
                if bar is not None:
                    bar.update(rcvd["progress"]-progress_dict["progress"])
                progress_dict = rcvd
                
            yield progress_dict
                
        # Either we completed everything or we manually stopped
        if bar is not None:
            bar.close()
            DataManager.stop_remote_server(address)
    