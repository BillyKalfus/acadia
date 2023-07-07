def next_highest_power_of_2(num, log=False):
    """
    Given an unsigned integer ``num``, returns the smallest power of 2 greater 
    than or equal to ``num``. Optionally, it can return the base-2 log of this
    number instead, representing the number of bits needed to store ``num``.

    :param num: Search limit
    :type num: int
    :param log: If ``True``, returns the base-2 log of the integer.
    """
    i = 0
    while (1 << i) < num:
        i += 1
    return (i if log else (1 << i))
