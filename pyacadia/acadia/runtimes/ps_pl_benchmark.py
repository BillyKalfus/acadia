from dataclasses import dataclass

from acadia.runtime import Runtime
from acadia.data import DataManager, PlotMixin, ArrayRecordGroup

class BenchmarkRecordGroup(ArrayRecordGroup, PlotMixin):
    
    def plot(self, fig):
        import numpy as np
        
        ax = fig.add_subplot(111)
        self.drawn = False
        
        def update(animation, framedata):    
            if self.records() is not None and not self.drawn:
                ax.hist(np.diff(self.records().flatten())[2:])
                self.drawn = True
                # print(self.records())
                    
        
        return update
                
@dataclass
class BenchmarkRuntime(Runtime):
    """
    A class for benchmarking communication latencies between the PS and the PL.    
    """
    
    trials: int
    test: str
    
    FILENAME = __file__
    
    tests = ["base_devmem", 
             "base_devmem_process", 
             "base_devmem_taskset", 
             "base_devmem_process_O3",
             "base_devmem_taskset_O0",
             "base_devmem_taskset_O1",
             "base_devmem_taskset_O2",
             "cache_devmem_taskset_O2",
             "base_kernel",
             "base_kernel_open"]
    
    def main(self, directory: str, datamanager: DataManager):
        import time
        import numpy as np
        import os
        import logging
        
        from acadia.system import Acadia
        from acadia.arrays import Array
        
        acadia = Acadia()
        
        timing_array = Array(np.uint32, length=self.trials)
        sync_array = Array(np.uint32, length=2, region=acadia.CacheArray)
                        
        # We'll collect the data traces in a record group
        timing_group = BenchmarkRecordGroup("timing", 
                                         directory,
                                         axes=[self.trials]) 
            
        datamanager.add_group(timing_group)
        
        # Create a sequence for the sequencer
        def sequence1(a):
            previous_value = a.sequencer().Register()
            previous_value.load(0xFFFFFFFF)
        
            timer = a.sequencer().DSP()
            timer.start_count(clear=True)
            
            with a.sequencer().loop():
                with a.sequencer().repeat_until(sync_array[0] != previous_value):
                    pass

                sync_array[1] = timer
                previous_value.load(sync_array[0])
        
        outfile_path = os.path.join(directory, f"{self.test}.bin")
        
        DEVMEM_CODE = f"""
            uint32_t read_data;
            uint32_t previous_value = 0xFFFFFFFF;
            uint32_t volatile *handshake;
            uint32_t outdata[{self.trials}] = {{0}};
            const char* outfile_path = "{outfile_path}";
            
            int memfd;
            FILE *outfile;
            
            memfd = open("/dev/mem", O_RDWR | O_SYNC);
            if(memfd == -1)
            {{
                return 1;
            }}
            
            handshake = (uint32_t*)mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, memfd, {sync_array.byte_address()});
            
            for(unsigned int i = 0; i < {self.trials}; i++)
            {{
                handshake[0] = i;
                while(read_data == previous_value) {{
                    read_data = handshake[1];
                }};
                outdata[i] = read_data;
                previous_value = read_data;   
            }}
            
            outfile = fopen(outfile_path, "w+");
            fwrite(outdata, sizeof(uint32_t), {self.trials}, outfile);
            fclose(outfile);
            
            close(memfd);
            
            return 0;
        """
        
        logging.info(f"Running test {self.test}")
        
        if self.test == "base_devmem":
            
            from cffi import FFI
            
            PROGRAM = f"""
                #include <sys/mman.h>
                #include <sys/stat.h>
                #include <fcntl.h>
                #include <stdio.h>
                #include <string.h>
                #include <stdlib.h>
                #include <stdint.h>
                #include <unistd.h>
                
                int run()
                {{
                    {DEVMEM_CODE}
                }}
            """
            
            logging.info("Compiling")
            
            ffi = FFI()
            ffi.set_source("_program", PROGRAM)
            ffi.cdef(f"int run(void);")
            ffi.compile(verbose=True)
            
            from _program import lib as program_lib
            
            logging.info("Running compiled process")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            program_lib.run()
            
            acadia.sequencer_halt()
            
            timing_array[:] = np.fromfile(outfile_path, np.uint32)
            datamanager.write("timing", timing_array)
            
        elif self.test == "base_devmem_process":            
            PROGRAM = f"""
                #include <sys/mman.h>
                #include <sys/stat.h>
                #include <fcntl.h>
                #include <stdio.h>
                #include <string.h>
                #include <stdlib.h>
                #include <stdint.h>
                #include <unistd.h>
                
                int main()
                {{
                    {DEVMEM_CODE}
                }}
            """
            
            with open(os.path.join(directory, "program.c"), "w") as f:
                f.write(PROGRAM)
                
            logging.info("Compiling")
                
            os.system(f"gcc -o program program.c")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("./program")
            
            acadia.sequencer_halt()
            
            timing_array[:] = np.fromfile(outfile_path, np.uint32)
            datamanager.write("timing", timing_array)
            
        elif self.test == "base_devmem_taskset":            
            PROGRAM = f"""
                #include <sys/mman.h>
                #include <sys/stat.h>
                #include <fcntl.h>
                #include <stdio.h>
                #include <string.h>
                #include <stdlib.h>
                #include <stdint.h>
                #include <unistd.h>
                
                int main()
                {{
                    {DEVMEM_CODE}
                }}
            """
            
            with open(os.path.join(directory, "program.c"), "w") as f:
                f.write(PROGRAM)
                
            logging.info("Compiling")
                
            os.system(f"gcc -o program program.c")
            
            acadia.attach()

            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("taskset -c 1 ./program")
            
            acadia.sequencer_halt()
            
            timing_array[:] = np.fromfile(outfile_path, np.uint32)
            datamanager.write("timing", timing_array)
            
        elif self.test == "base_devmem_process_O3":
            
            PROGRAM = f"""
                #include <sys/mman.h>
                #include <sys/stat.h>
                #include <fcntl.h>
                #include <stdio.h>
                #include <string.h>
                #include <stdlib.h>
                #include <stdint.h>
                #include <unistd.h>
                
                int main()
                {{
                    {DEVMEM_CODE}
                }}
            """
            
            with open(os.path.join(directory, "program.c"), "w") as f:
                f.write(PROGRAM)
                
            logging.info("Compiling")
                
            os.system(f"gcc -O3 -o program program.c")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("./program")
            
            acadia.sequencer_halt()
            
            timing_array[:] = np.fromfile(outfile_path, np.uint32)
            datamanager.write("timing", timing_array)
            
        elif self.test.startswith("base_devmem_taskset_O"):            
            PROGRAM = f"""
                #include <sys/mman.h>
                #include <sys/stat.h>
                #include <fcntl.h>
                #include <stdio.h>
                #include <string.h>
                #include <stdlib.h>
                #include <stdint.h>
                #include <unistd.h>
                
                int main()
                {{
                    {DEVMEM_CODE}
                }}
            """
            
            with open(os.path.join(directory, "program.c"), "w") as f:
                f.write(PROGRAM)
                
            logging.info("Compiling")
                
            os.system(f"gcc -fno-asynchronous-unwind-tables -fno-dwarf2-cfi-asm -fno-exceptions -fno-rtti -S -O{self.test[-1]} -o program.s program.c")
            os.system(f"gcc -c program.s -o program.o")
            os.system(f"gcc -o program program.o")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("taskset -c 1 ./program")
            
            acadia.sequencer_halt()
            
            timing_array[:] = np.fromfile(outfile_path, np.uint32)
            datamanager.write("timing", timing_array.memory)
            
        elif self.test.startswith("cache_devmem_taskset_O"):            
            PROGRAM = f"""
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>

int main()
{{
    uint32_t read_data;
    uint32_t previous_value = 0xFFFFFFFF;
    uint32_t volatile *handshake;
    
    int memfd;
    
    memfd = open("/dev/mem", O_RDWR | O_SYNC);
    if(memfd == -1)
    {{
        return 1;
    }}
    
    handshake = (uint32_t*)mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, memfd, {sync_array.byte_address()});
    
    for(unsigned int i = 0; i < {self.trials}; i++)
    {{
        handshake[0] = i;
        while(read_data == previous_value) {{
            read_data = handshake[1];
        }};
        previous_value = read_data;   
    }}
    
    close(memfd);
    
    return 0;
}}
"""

            cache_timing_array = Array(np.uint32, length=self.trials, region=acadia.CacheArray)

            def sequence2(a):
                previous_value = a.sequencer().Register()
                previous_value.load(0xFFFFFFFF)
            
                timer = a.sequencer().DSP()
                timer.start_count(clear=True)
                
                with a.sequencer().loop():
                    with a.sequencer().repeat_until(sync_array[0] != previous_value):
                        pass
                        
                    previous_value.load(sync_array[0])
                    sync_array[1] = previous_value
                    cache_timing_array[previous_value] = timer
            
            with open(os.path.join(directory, "program.c"), "w") as f:
                f.write(PROGRAM)
                
            logging.info("Compiling")
                
            os.system(f"gcc -fno-asynchronous-unwind-tables -fno-dwarf2-cfi-asm -fno-exceptions -fno-rtti -S -O{self.test[-1]} -o program.s program.c")
            os.system(f"gcc -c program.s -o program.o")
            os.system(f"gcc -o program program.o")
            
            acadia.attach()
            
            sync_array[0] = 0xFFFFFFFF
            sync_array[1] = 0xFFFFFFFF
            
            acadia.compile(sequence2)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("taskset -c 1 ./program")
            
            acadia.sequencer_halt()
            
            datamanager.write("timing", cache_timing_array.memory)
            
        elif self.test == "base_kernel":
            
            MODULE = f"""
#include <linux/atomic.h> 
#include <linux/cdev.h> 
#include <linux/delay.h> 
#include <linux/device.h> 
#include <linux/fs.h> 
#include <linux/init.h> 
#include <linux/ioport.h>
#include <linux/kernel.h> 
#include <linux/module.h> 
#include <linux/printk.h> 
#include <linux/types.h> 
#include <linux/uaccess.h> 
#include <linux/version.h> 

#include <asm/errno.h> 
#include <asm/io.h> 

static int device_open(struct inode *, struct file *); 
static int device_release(struct inode *, struct file *); 
static ssize_t device_read(struct file *, char __user *, size_t, loff_t *); 
static ssize_t device_write(struct file *, const char __user *, size_t, 
                            loff_t *); 

#define DEVICE_NAME "acadiabenchmark" /* Dev name as it appears in /proc/devices   */ 
                
static int major; /* major number assigned to our device driver */ 
                
static struct class *cls; 

static struct file_operations chardev_fops = {{ 
    .read = device_read, 
    .write = device_write, 
    .open = device_open, 
    .release = device_release, 
}}; 

static unsigned int outdata[{self.trials}];

static int __init chardev_init(void) 
{{ 
    unsigned int read_data = 0xFFFFFFFF;
    unsigned int previous_value = 0xFFFFFFFF;
    volatile unsigned int *sync_array;
    unsigned int i;
    
    major = register_chrdev(0, DEVICE_NAME, &chardev_fops); 

    if (major < 0) {{ 
        pr_alert("Registering char device failed with %d\\n", major); 
        return major; 
    }}

    pr_info("I was assigned major number %d.\\n", major);
    cls = class_create(THIS_MODULE, DEVICE_NAME); 
    device_create(cls, NULL, MKDEV(major, 0), NULL, DEVICE_NAME); 
    pr_info("Device created on /dev/%s\\n", DEVICE_NAME); 
    
    request_mem_region({sync_array.byte_address()}, {sync_array.byte_length()}, DEVICE_NAME);
    sync_array = (volatile unsigned int*)ioremap_nocache({sync_array.byte_address()}, {sync_array.byte_length()});
    
    for(i = 0; i < {self.trials}; i++)
    {{
        writel(i, sync_array);
        wmb();
        while(read_data == previous_value) {{
            read_data = readl(sync_array + 1);
            rmb();
        }};
        outdata[i] = read_data;
        previous_value = read_data;   
    }}
    
    pr_info("Test completed\\n"); 
    
    release_mem_region({sync_array.byte_address()}, {sync_array.byte_length()});
    
    iounmap(sync_array);

    return 0; 
}} 

static void __exit chardev_exit(void) 
{{ 
    device_destroy(cls, MKDEV(major, 0)); 
    class_destroy(cls);                 
    unregister_chrdev(major, DEVICE_NAME); 
}}

static int device_open(struct inode *inode, struct file *file) 
{{                
    try_module_get(THIS_MODULE);                 
    return 0; 
}}

static int device_release(struct inode *inode, struct file *file) 
{{
    module_put(THIS_MODULE); 
    return 0; 
}}

static ssize_t device_read(struct file *filp, /* see include/linux/fs.h   */ 
                        char __user *buffer, /* buffer to fill with data */ 
                        size_t length, /* length of the buffer     */ 
                        loff_t *offset) 
{{ 
    int bytes_read = 0;

    if(*offset >= {self.trials}*sizeof(unsigned int)) {{
        *offset = 0;
        return 0;
    }}
                    
    while (length-- && *offset < {self.trials}*sizeof(unsigned int)) {{ 
        put_user(*((char*)outdata + *offset), buffer++); 
        bytes_read++;
        *offset = *offset + 1;
    }} 
                
    return bytes_read; 
}} 

static ssize_t device_write(struct file *filp, const char __user *buff, 
                            size_t len, loff_t *off) 
{{ 
    pr_alert("Sorry, this operation is not supported.\\n"); 
    return -EINVAL; 
}}

module_init(chardev_init); 
module_exit(chardev_exit); 

MODULE_LICENSE("GPL");
            """
            
            MAKEFILE = f"""
obj-m += acadia_module.o 
CFLAGS_acadia_module.o := -O3
CFLAGS_acadia_module.mod.o := -O3

PWD := $(CURDIR) 

all: 
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) V=1 modules 

clean: 
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean
            """
            
            with open(os.path.join(directory, "acadia_module.c"), "w") as f:
                f.write(MODULE)
                
            with open(os.path.join(directory, "Makefile"), "w") as f:
                f.write(MAKEFILE)
                
            logging.info("Compiling")
                
            os.system(f"make")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
            
            logging.info("Running compiled process")
            os.system("insmod acadia_module.ko")
            
            acadia.sequencer_halt()
            
            logging.info("Reading result")
            with open("/dev/acadiabenchmark", "rb") as f:
                data = f.read()
                        
            datamanager.write("timing", np.frombuffer(data, np.uint32))
            
            os.system("rmmod acadia_module")
            
        elif self.test == "base_kernel_open":
            
            MODULE = f"""
#include <linux/atomic.h> 
#include <linux/cdev.h> 
#include <linux/delay.h> 
#include <linux/device.h> 
#include <linux/fs.h> 
#include <linux/init.h> 
#include <linux/ioport.h>
#include <linux/kernel.h> 
#include <linux/module.h> 
#include <linux/printk.h> 
#include <linux/types.h> 
#include <linux/uaccess.h> 
#include <linux/version.h> 

#include <asm/errno.h> 
#include <asm/io.h> 

static int device_open(struct inode *, struct file *); 
static int device_release(struct inode *, struct file *); 
static ssize_t device_read(struct file *, char __user *, size_t, loff_t *); 
static ssize_t device_write(struct file *, const char __user *, size_t, 
                            loff_t *); 

#define DEVICE_NAME "acadiabenchmark" /* Dev name as it appears in /proc/devices   */ 
                
static int major; /* major number assigned to our device driver */ 
                
static struct class *cls; 

static struct file_operations chardev_fops = {{ 
    .read = device_read, 
    .write = device_write, 
    .open = device_open, 
    .release = device_release, 
}}; 

static unsigned int outdata[{self.trials}];

static int __init chardev_init(void) 
{{  
    major = register_chrdev(0, DEVICE_NAME, &chardev_fops); 

    if (major < 0) {{ 
        pr_alert("Registering char device failed with %d\\n", major); 
        return major; 
    }}

    pr_info("I was assigned major number %d.\\n", major);
    cls = class_create(THIS_MODULE, DEVICE_NAME); 
    device_create(cls, NULL, MKDEV(major, 0), NULL, DEVICE_NAME); 
    pr_info("Device created on /dev/%s\\n", DEVICE_NAME); 

    return 0; 
}} 

static void __exit chardev_exit(void) 
{{ 
    device_destroy(cls, MKDEV(major, 0)); 
    class_destroy(cls);                 
    unregister_chrdev(major, DEVICE_NAME); 
}}

static int device_open(struct inode *inode, struct file *file) 
{{                
    try_module_get(THIS_MODULE);   
    
    unsigned int read_data = 0xFFFFFFFF;
    unsigned int previous_value = 0xFFFFFFFF;
    volatile unsigned int *sync_array;
    unsigned int i;
    
    request_mem_region({sync_array.byte_address()}, {sync_array.byte_length()}, DEVICE_NAME);
    sync_array = (volatile unsigned int*)ioremap_nocache({sync_array.byte_address()}, {sync_array.byte_length()});
    
    for(i = 0; i < {self.trials}; i++)
    {{
        writel(i, sync_array);
        wmb();
        while(read_data == previous_value) {{
            read_data = readl(sync_array + 1);
            rmb();
        }};
        outdata[i] = read_data;
        previous_value = read_data;   
    }}
    
    pr_info("Test completed\\n"); 
    
    release_mem_region({sync_array.byte_address()}, {sync_array.byte_length()});
    
    iounmap(sync_array);
                  
    return 0; 
}}

static int device_release(struct inode *inode, struct file *file) 
{{
    module_put(THIS_MODULE); 
    return 0; 
}}

static ssize_t device_read(struct file *filp, /* see include/linux/fs.h   */ 
                        char __user *buffer, /* buffer to fill with data */ 
                        size_t length, /* length of the buffer     */ 
                        loff_t *offset) 
{{ 
    int bytes_read = 0;

    if(*offset >= {self.trials}*sizeof(unsigned int)) {{
        *offset = 0;
        return 0;
    }}
                    
    while (length-- && *offset < {self.trials}*sizeof(unsigned int)) {{ 
        put_user(*((char*)outdata + *offset), buffer++); 
        bytes_read++;
        *offset = *offset + 1;
    }} 
                
    return bytes_read; 
}} 

static ssize_t device_write(struct file *filp, const char __user *buff, 
                            size_t len, loff_t *off) 
{{ 
    pr_alert("Sorry, this operation is not supported.\\n"); 
    return -EINVAL; 
}}

module_init(chardev_init); 
module_exit(chardev_exit); 

MODULE_LICENSE("GPL");
            """
            
            MAKEFILE = f"""
obj-m += acadia_module.o 
CFLAGS_acadia_module.o := -O3
CFLAGS_acadia_module.mod.o := -O3

PWD := $(CURDIR) 

all: 
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) V=1 modules 

clean: 
\tmake -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean
            """
            
            with open(os.path.join(directory, "acadia_module.c"), "w") as f:
                f.write(MODULE)
                
            with open(os.path.join(directory, "Makefile"), "w") as f:
                f.write(MAKEFILE)
                
            logging.info("Compiling")
                
            os.system(f"make")
            
            acadia.attach()
            
            sync_array[0] = 0xDEADBEEF
            sync_array[1] = 0xDEADBEEF
            
            acadia.compile(sequence1)
            acadia.run(block=False)
        
            os.system("insmod acadia_module.ko")
            
            logging.info("Running compiled process")
            with open("/dev/acadiabenchmark", "rb") as f:
                logging.info("Reading result")
                data = f.read()
                
            acadia.sequencer_halt()
                        
            datamanager.write("timing", np.frombuffer(data, np.uint32))
            
            os.system("rmmod acadia_module")
    
        else:
            raise ValueError(f"Unrecognized test {self.test}")

        
        
        