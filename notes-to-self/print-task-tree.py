import trio
import trio.testing

MID_PREFIX = "├─ "
MID_CONTINUE = "│  "
END_PREFIX = "└─ "
END_CONTINUE = " " * len(END_PREFIX)


def current_root_task():
    task = trio.hazmat.current_task()
    while task.parent_nursery is not None:
        task = task.parent_nursery.parent_task
    return task


def _render_subtree(name, rendered_children):
    lines = []
    lines.append(name)
    for child_lines in rendered_children:
        if child_lines is rendered_children[-1]:
            first_prefix = END_PREFIX
            rest_prefix = END_CONTINUE
        else:
            first_prefix = MID_PREFIX
            rest_prefix = MID_CONTINUE
        lines.append(first_prefix + child_lines[0])
        for child_line in child_lines[1:]:
            lines.append(rest_prefix + child_line)
    return lines


def _rendered_nursery_children(nursery):
    return [task_tree_lines(t) for t in nursery.child_tasks]


def task_tree_lines(task=None):
    if task is None:
        task = current_root_task()
    rendered_children = []
    nurseries = list(task.child_nurseries)
    while nurseries:
        nursery = nurseries.pop()
        nursery_children = _rendered_nursery_children(nursery)
        if rendered_children:
            nested = _render_subtree("(nested nursery)", rendered_children)
            nursery_children.append(nested)
        rendered_children = nursery_children
    return _render_subtree(task.name, rendered_children)


def print_task_tree(task=None):
    for line in task_tree_lines(task):
        print(line)


################################################################


async def child2():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(trio.sleep_forever)
        nursery.start_soon(trio.sleep_forever)


async def child1():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(child2)
        nursery.start_soon(child2)
        nursery.start_soon(trio.sleep_forever)


async def main():
    async with trio.open_nursery() as nursery0:
        nursery0.start_soon(child1)
        async with trio.open_nursery() as nursery1:
            nursery1.start_soon(child1)

            await trio.testing.wait_all_tasks_blocked()
            print_task_tree()
            nursery0.cancel_scope.cancel()


trio.run(main)
