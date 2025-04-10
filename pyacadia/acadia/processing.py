import logging
import os
import json
import inspect
from datetime import datetime, timezone
from typing import Union

import numpy as np

from acadia.data import DataManager

def process_data(source, dimensions=None):
    """
    A helper function for retrieving and processing data. 

    The parameter ``source`` specifies the origin of the data, depending 
    on its type:
    
    - If a tuple of (:class:`DataManager`, str), this indicates that data
        should be extracted from the :class:`DataManager` in the first 
        element using the record name given by the second.

    - If a :class:`RecordGroup`, this indicates that the data should be 
        extracted by calling that object's `records()` method.

    - If a :class:`np.ndarray`, this is used as the data directly.

    The retrieved data is always flattened, and the ``dimensions`` sequence
    parameter describes how it should be reshaped and processed. This must 
    contain one element per dimension of the reshaped data, and each element  
    must be a tuple with the following two elements:

    - An object specifying the length of the data in the dimension. If an 
        ``int``, this is used as the length. If an object defining 
        ``__len__``, its return value is used as the length of the 
        corresponding dimension. At most one dimension may use ``-1`` for
        this parameter, in which case the length of data in that dimension 
        is inferred via the amount of data available.

    - An object specifying how to reduce the data across the dimension. If
        ``None``, no reduction is performed and all data along the 
        corresponding dimension is returned. If an ``int``, the data at the
        corresponding index along the dimension's axis is used. If an 
        object defining ``__len__``, the data at the indices specified by 
        the elements of this parameter is used. If an object of type 
        ``np.ufunc``, the data is reduced along the corresponding dimension
        using the function. If an object defining ``__call__`` (which 
        isn't of type ``np.ufunc``), the object is called with the data 
        array provided as the first (and only) positional argument and 
        ``axis`` provided as the only keyword argument, populated with the
        axis number that this callable was provided for.

    """
    logger = logging.getLogger()

    if isinstance(source, tuple) and len(source) == 2 and isinstance(source[0], DataManager) and isinstance(source[1], str):
        data = source[0][source[1]].records()
    elif isinstance(source, np.ndarray):
        data = source
    else:
        raise TypeError(f"Unable to interpret data source {type(source)}")

    logger.debug(f"Processing data of type {data.dtype} with {data.size} elements")

    if dimensions is None:
        return data, data.shape
    
    if not hasattr(dimensions, "__len__"):
        raise TypeError(f"Dimension-specifying parameter must be sequence-like;"
                        f" found type {type(dimensions)}")
    
    if len(dimensions) == 0:
        return data, data.shape

    # Get rid of any partial datasets
    # If none of the lengths are -1, an extra dimension will be added
    dataset_shape = tuple(len(e) if hasattr(e, "__len__") else e for e,_ in dimensions)
    dataset_size = np.prod(dataset_shape)

    if dataset_size < 0:
        # One of the dimensions is -1
        # Here, we'll only use the total number of datasets to determine how many
        # elements we need to discard
        dataset_size *= -1
        num_datasets = data.size // dataset_size
        elements_to_keep = num_datasets*dataset_size
        return_data = data.reshape(-1)[:elements_to_keep].reshape(*dataset_shape)
    else:
        # Add a dimension to the beginning to index over complete datasets
        num_datasets = data.size // dataset_size
        elements_to_keep = num_datasets*dataset_size
        return_data = data.reshape(-1)[:elements_to_keep].reshape(num_datasets, *dataset_shape)

    shape_before_reduction = return_data.shape

    logger.debug(f"Found {num_datasets} datasets using shape {dataset_shape}"
                    f" (size {dataset_size}), with {data.size - elements_to_keep}"
                    f" elements left over. Final shape before reduction:"
                    f" {shape_before_reduction}")

    # Iterate in reverse order, since reducing over axes whose elements are
    # consecutive in memory will be much faster
    for axis,(_,reducer) in reversed(list(enumerate(dimensions))):
        if isinstance(reducer, np.ufunc):
            return_data = reducer.reduce(return_data, axis=axis)

            # Add back in the trivial axis that was reduced (so as not to 
            # confuse the axis numbers in following iterations)
            return_data = np.expand_dims(return_data, axis)
        elif isinstance(reducer, (int, list, tuple, np.ndarray)):
            return_data = np.take(return_data, reducer, axis=axis)
        elif hasattr(reducer, "__call__"):
            return_data = reducer(return_data, axis=axis)
        elif reducer is not None:
            raise TypeError(f"Unable to reduce dimension {axis} with object"
                            f" of type {type(reducer)}")

    return return_data, shape_before_reduction


class DynamicLine:
    """
    A simple wrapper for dynamically updating plots rendered by calls to 
    :meth:`Axes.plot()`.
    """

    def __init__(self, ax, fmt="-", **kwargs):
        """
        Add the line to a pyplot axis. All arguments (except for the axis) 
        will be passed directly to `Axes.plot()`

        :param ax: Axis to add to
        :type ax: matplotlib.pyplot.Axes
        """
        self._ax = ax
        self.retval = ax.plot([], [], fmt, **kwargs)

    def update(self, xdata, ydata, 
               rescale_axis=True,
               ylim_top:Union[str, float]='auto', 
               ylim_bottom:Union[str, float]='auto' 
               ):
        """
        Update the data contained in a line created by calling `Axis.plot`. 
        
        :param plot_retval: Value returned by `plot` #Billy is this supposed to be here
        :type plot_retval: tuple
        
        :param ylim_top: 
    
        :param ylim_bottom: 
        
        
        """
        self.retval[0].set_data(xdata, ydata)
        if rescale_axis:
            xlim = self._ax.get_xlim()
            xmin = np.min(xdata)
            xmax = np.max(xdata)
            if (xmin != xlim[0] or xmax != xlim[1]) and xmin != xmax:
                self._ax.set_xlim(xmin, xmax)
            
            if (ylim_top == "auto") and (ylim_bottom=="auto"):
                self._ax.relim()
                self._ax.autoscale(axis='y')
                return

            ylim = self._ax.get_ylim()
            if ylim_bottom == 'auto':
                ymin = np.min(ydata)
            else:
                ymin = ylim_bottom
            
            if ylim_top == 'auto':
                ymax = np.max(ydata)
            else:
                ymax = ylim_top
                
            if (ymin != ylim[0] or ymax != ylim[1]) and ymin != ymax:
                self._ax.set_ylim(ymin, ymax)

    def get_data(self):
        return self.retval[0].get_data()

class DynamicErrorbar:

    def __init__(self, ax, fmt="-", **kwargs):
        """
        Add the line to a pyplot axis. All arguments (except for the axis) 
        will be passed directly to `Axes.plot()`

        :param ax: Axis to add to
        :type ax: matplotlib.pyplot.Axes
        """
        self.retval = ax.errorbar([], [], fmt, yerr=[], **kwargs)

    def update(self, xdata, ydata, yerr):
        """
        Update the curve and error data on an errorbar.
        """
        ln,err,bars = self.retval
        ln.set_data(xdata, ydata)
        
        new_errorbars = [[[x,ydata[i]-yerr[i]],
                          [x,ydata[i]+yerr[i]]] for i,x in enumerate(xdata)]
        
        bars[0].set_segments([np.array(points) for points in new_errorbars])
        
class ProgressBar:
    def __init__(self, total=None, label=None):        
        from tqdm.notebook import tqdm
        self.bar = tqdm(desc=label, dynamic_ncols=True, total=total)
        self._last_count = 0

    def update(self, group):
        """
        Update the progress bar from the value in a :class:`RecordGroup`.
        """
        if self.bar.desc is None:
            self.bar.desc = group._name
            self.bar.refresh()

        self.bar.update(group[0] - self._last_count)
        self._last_count = group[0]
            
    def finalize(self):
        self.bar.close()
    
def set_scientific_notation(plot_axis):
    '''
    Enforce displaying scientific notation on a pyplot axis.
    Example use context:
    
    set_scientific_notation(ax.yaxis)
    '''
    
    from matplotlib import ticker
    formatter = ticker.ScalarFormatter(useMathText=True)
    formatter.set_scientific(True) 
    formatter.set_powerlimits((-1,1))
    plot_axis.set_major_formatter(formatter)
        
