from ... import _core
from .._parking_lot import ParkingLot

async def test_parking_lot_basic():
    record = []
    async def waiter(i, lot):
        record.append("sleep {}".format(i))
        val = await lot.park()
        record.append("wake {} = {}".format(i, val))

    lot = ParkingLot()
    for i in range(3):
        await _core.spawn(waiter, i, lot)
    while len(record) != 3:
        await _core.yield_briefly()
    # default is to wake all
    lot.unpark(result=_core.Value(17))
    while len(record) != 6:
        await _core.yield_briefly()

#
