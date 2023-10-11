import os
import logging
from threading import Thread, Event
from functools import partial
from abc import ABC, abstractstaticmethod, abstractmethod

__all__ = ["Runtime"]

class Runtime(ABC):
    """
    An organization class for orchestrating the deployment of programs
    """
    
    def __init__(self, 
                 target_ip, 
                 filename,
                 target_port=6672, 
                 jump_server=None, 
                 plot_update_period=0.1,
                 progress_update_period=0.1):
        self._target_ip = target_ip
        self._target_port = target_port
        self._jump_server = jump_server
        self._plot_thread = None
        self._plot_update_period = plot_update_period
        self._progress_update_period = progress_update_period
        self._progress_thread = None
        self._proc = None
        self._filename = filename
        
    def run(self, block="process"):
        """
        Deploy the procedure described by the class on a remote target.
        Note that key-based authentication MUST be configured on the target
        prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done once.       
        
        :param block: If `"progress"`, this method will block until the 
            :class:`DataManager` running on the target provides a progress
            update indicating that all iterations have completed. Note that 
            this requires the iterator passed to `DataManager.progress` to 
            define `__len__` so that the server can determine completion.
            If `"process"`, this will block until the remote process is 
            complete. If `None`, the method will return after starting all 
            required threads without waiting.
        :type block: bool
        :param close: If both `close` and `block` are `True`, :meth:``stop``
            will be called when the server indicates completion.
        """ 
        # Deploy a process on the target that will call main()
        import subprocess
        
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
        python_cmd = f"python3 -c \"f = open(\\\"/home/root/{os.path.basename(self._filename)}\\\", \\\"rb\\\"); exec(f.read()); f.close(); {cls}.main()\""
        
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
        
        fig,update_func = self.plot()
        
        # If we have a plot, launch a thread that will update plotting as well as a progress bar
        if fig is not None and update_func is not None:
            # Create a generator that will let us gracefully stop if requested 
            # by the main thread
            def frame_generator():
                import time
                frame_num = 0
                while True:
                    time.sleep(self._plot_update_period)
                    if self._stop_event.is_set():
                        break
                    frame_num += 1
                    
                    yield frame_num
            
            # Create the animation in a new thread
            def thread_func():     
                from matplotlib.animation import FuncAnimation   
                self._anim = FuncAnimation(fig, 
                              partial(update_func, (self._target_ip, self._target_port)), 
                              frames=frame_generator, 
                              repeat=False, 
                              blit=True)
                
                
            self._plot_thread = Thread(target=thread_func, name="PlotThread", daemon=True)
            self._plot_thread.start()
            
        # Create a progress tracker thread
        if self._progress_update_period <= 0:
            raise ValueError("Must provide positive progress update period")
        
        def _progress_thread():
            # Repeatedly ask for progress until we get a valid progress 
            # dictionary from the server
            from acadia.data import DataManager
            import time
            from tqdm.notebook import tqdm
            
            logging.debug("Progress monitoring thread started")
            
            progress_dict = {}
            while len(progress_dict) == 0:
                if self._stop_event.is_set():
                    return
                time.sleep(self._progress_update_period)
                rcvd = DataManager.receive_counters((self._target_ip, self._target_port))
                if rcvd is not None:
                    progress_dict = rcvd
                    
            if block and "total" not in progress_dict:
                raise ValueError("Cannot call `run` with `block=True` when the"
                                 " remote `DataManager` does not provide a"
                                 " total number of iterations.")
                    
            logging.debug(f"Creating progress bar with state {rcvd}")
                                       
            bar = tqdm(total=progress_dict["total"], position=progress_dict["progress"])
            
            while (progress_dict["progress"] < progress_dict["total"]) and self._proc.poll() is None:
                if self._stop_event.is_set():
                    break
                time.sleep(self._progress_update_period)
                rcvd = DataManager.receive_counters((self._target_ip, self._target_port))
                if rcvd is not None:
                    bar.update(rcvd["progress"]-progress_dict["progress"])
                    progress_dict = rcvd
                    
            # We've received everything
            bar.close()
                
        self._progress_thread = Thread(target=_progress_thread, 
                                        daemon=True, 
                                        name="ProgressThread")
        self._progress_thread.start()
            
        if block == "progress":
            logging.info("Waiting for progress completion.")
            self._progress_thread.join()
            self._progress_thread = None
            self.stop()
        elif block == "process":
            logging.info("Awaiting process completion.")
            while self._proc.poll() is None:
                pass
        elif block is not None:
            raise ValueError(f"Unrecognized blocking mode {block}; stopping.")
            
        self.stop()    
        
    def stop(self):
        """
        Gracefully stop any running process.
        """
        if self._proc is None:
            # We never started
            return
        
        # Request the data manager server to stop
        from acadia.data import DataManager
        DataManager.stop_remote_server((self._target_ip, self._target_port))
        
        if self._proc.poll() is None:
            # The process is still running, kill it
            self._proc.kill()
            
        # Stop any child threads that we may have started
        self._stop_event.set()
        
        if self._plot_thread is not None:
            self._plot_thread.join()
        if self._progress_thread is not None:
            self._progress_thread.join()
        
    @abstractstaticmethod
    def main():
        """
        A function that will be run on the target upon deployment.
        """
        pass
    
    def plot(self):
        """
        This function should initialize any figures or other graphical objects
        and return a function that will update them along with the primary
        ``Figure`` object. This function must accept an integer as its second
        argument, which will be populated with the frame number, and a tuple
        as its first argument, which will be populated with the target's IP
        address and port.
        """
        return None, None            
    
    