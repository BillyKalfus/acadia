import os
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
                 plot_update_period=0.1):
        self._target_ip = target_ip
        self._target_port = target_port
        self._jump_server = jump_server
        self._plot_update_period = plot_update_period
        self._proc = None
        self._filename = filename
        
    def run(self):
        """
        Deploy the procedure described by the class on a remote target.
        Note that key-based authentication MUST be configured on the target
        prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done once.        
        """ 
        # Deploy a process on the target that will call main()
        import subprocess
        
        # Copy over the subclass file
        subprocess.run(['scp', 
                        f'{self._filename}', 
                        f'root@{self._target_ip}:/home/root'], 
                       check=True, 
                       capture_output=True)
        
        args = ["ssh"]
        
        if self._jump_server is not None:
            args += ["-J", self._jump_server]
            
        cls = self.__class__.__name__
        python_cmd = f"python3 -c \"f = open('/home/root/{os.path.basename(self._filename)}', 'rb'); exec(f.read()); f.close(); {cls}.main()\""
        args += [f"root@{self._target_ip}", f"{python_cmd}"]
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, )
        
        # Launch the plotting
        fig,update_func = self.plot()
        
        if fig is not None and update_func is not None:
            # Create a generator that will let us gracefully stop if requested 
            # by the main thread
            self._stop_event = Event()
            def frame_generator():
                frame_num = 0
                while True:
                    if self._stop_event.is_set():
                        break
                    frame_num += 1
                    
                    yield frame_num
            
            # Create the animation in a new thread
            from matplotlib.animation import FuncAnimation
            
            def thread_func():        
                self._anim = FuncAnimation(fig, 
                              partial(update_func, (self._target_ip, self._target_port)), 
                              frames=frame_generator, 
                              repeat=False, 
                              blit=True)
                
                
            self._plot_thread = Thread(target=thread_func, name="PlotThread", daemon=True)
            self._plot_thread.start()
        else:
            self._plot_thread = None
            self._stop_event = None
        
    def stop(self):
        """
        Gracefully stop any running process.
        """
        if self._proc is None:
            # We never started
            return
        
        if self._proc.poll() is None:
            # The process is still running, kill it
            self._proc.kill()
            
        # Stop the plotting thread if we started one
        if self._stop_event is not None:
            self._stop_event.set()
            self._plot_thread.join()
        
    @abstractstaticmethod
    def main():
        """
        A function that will be run on the target upon deployment.
        """
        pass
    
    @abstractmethod
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
    
    