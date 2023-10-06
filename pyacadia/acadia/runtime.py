from abc import ABC, abstractmethod, abstractstaticmethod

class Runtime(ABC):
    """
    An organization class for orchestrating the deployment of programs
    """
    
    def __init__(self, target_ip, target_port=6672, jump_server=None, plot_update_period=0.1):
        self._target_ip = target_ip
        self._target_port = target_port
        self._jump_server = jump_server
        self._plot_update_period = plot_update_period
        
    def run(self):
        """
        Deploy the procedure described by the class on a remote target.
        Note that key-based authentication MUST be configured on the target
        prior to deployment. This can be done by executing 
        
            ``ssh-copy-id username@target``
            
        on the host. This only needs to be done once.        
        """ 
        # First, deploy a process on the target that will call main()
        import subprocess
        
        args = ["ssh"]
        
        if self._jump_server is not None:
            args += [""]
        
        subprocess.run
        
        
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
        and return a function that will update them.
        """
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    
    
    