import attr

# you know maybe it would be better if the ability to spawn children was more
# tightly controlled. it really doesn't make sense to *nest* supervisors, and
# there's all kinds of horribleness likely if, like, you have a supervisor
# that's trying to monitor children explicitly with a queue, but then a
# higher-up supervisor *doesn't* have a queue registered so the lower-down
# supervisor is getting random ChildCrashed exceptions thrown into it.
#
# So like maybe you have to explictly create a supervisor context if you want
# to spawn at all?
#
# give unboundedqueue a push_back_all_nowait method to push back entries onto
# the queue that we don't want to process now
# anything in the queue when we get back to __exit__ will be processed there
#
# if you want to process the queue, cool, otherwise, just spawn your initial
# children and then park in __exit__ to get its default handling.

# 2-way proxy:
async with supervisor() as s:
    await s.spawn(copy_all, a, b)
    await s.spawn(copy_all, b, a)

async def race(candidates):
    async with task_group() as tg:
        for candidate in candidates:
            await tg.spawn(*candidate)
        batch = await tg.monitor.get_all()
        tg.monitor.unget_all_nowait(batch[1:])
        tg.cancel_all()
        return batch[0].unwrap()

# if any raise, cancels the remainder and raises an aggregate exception
async def concurrent_map(fn, iterable):
    async with task_group() as tg:
        tasks = {}
        for i, obj in enumerate(iterable):
            tasks[i] = await tg.spawn(fn, obj)
        results = [None] * len(tasks)
        async for task_batch in tg.monitor:
            for task in task_batch:
                results[tasks[task]] = task.result.unwrap()
    return results

# Handles cancellation by cancelling everything and then raising an aggregate
# error; otherwise returns a list of Results.
# Hmm, this is kinda broken in that if we are cancelled or otherwise error out
# we don't want an aggregate error, we want to discard child task errors.
async def concurrent_map_results(fn, iterable):
    async with task_group() as tg:
        try:
            tasks = {}
            for i, obj in enumerate(iterable):
                tasks[i] = await tg.spawn(fn, obj)
            results = [None] * len(tasks)
            async for task_batch in tg.monitor:
                for task in task_batch:
                    results[tasks[task]] = task.result
        except:
            tg.cancel_all()
            # maybe?
            await tg.wait()
            # or?
            while tg.tasks:
                await tg.monitor.get_all()
            raise
    return results

