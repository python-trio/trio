from __future__ import annotations

import builtins
import enum
import inspect
import re
import socket
import sys
from pathlib import Path
from pprint import pprint
from typing import TYPE_CHECKING, Any, Iterator

import pytest
import yaml  # type: ignore

import trio
from trio.tests.test_exports import PUBLIC_MODULES

# all publicly exported objects currently without attention. Entries in this
# set should gradually be removed as more of the codebase is typed.
# try to keep it sorted for readability
HAS_NO_ANNOTATION: set[str] = {
    "trio.CancelScope",
    "trio.CancelScope.cancel",
    "trio.CancelScope.cancel_called",
    "trio.CancelScope.deadline",
    "trio.CancelScope.shield",
    "trio.CapacityLimiter",
    "trio.CapacityLimiter.acquire",
    "trio.CapacityLimiter.acquire_nowait",
    "trio.CapacityLimiter.acquire_on_behalf_of",
    "trio.CapacityLimiter.acquire_on_behalf_of_nowait",
    "trio.CapacityLimiter.available_tokens",
    "trio.CapacityLimiter.borrowed_tokens",
    "trio.CapacityLimiter.release",
    "trio.CapacityLimiter.release_on_behalf_of",
    "trio.CapacityLimiter.statistics",
    "trio.CapacityLimiter.total_tokens",
    "trio.Condition",
    "trio.Condition.acquire",
    "trio.Condition.acquire_nowait",
    "trio.Condition.locked",
    "trio.Condition.notify",
    "trio.Condition.notify_all",
    "trio.Condition.release",
    "trio.Condition.statistics",
    "trio.Condition.wait",
    "trio.DTLSChannel",
    "trio.DTLSChannel.aclose",
    "trio.DTLSChannel.close",
    "trio.DTLSChannel.do_handshake",
    "trio.DTLSChannel.get_cleartext_mtu",
    "trio.DTLSChannel.receive",
    "trio.DTLSChannel.send",
    "trio.DTLSChannel.set_ciphertext_mtu",
    "trio.DTLSChannel.statistics",
    "trio.DTLSEndpoint",
    "trio.DTLSEndpoint.close",
    "trio.DTLSEndpoint.connect",
    "trio.DTLSEndpoint.serve",
    "trio.Event",
    "trio.Event.is_set",
    "trio.Event.set",
    "trio.Event.statistics",
    "trio.Event.wait",
    "trio.Lock",
    "trio.Lock.acquire",
    "trio.Lock.acquire_nowait",
    "trio.Lock.locked",
    "trio.Lock.release",
    "trio.Lock.statistics",
    "trio.Nursery",
    "trio.Nursery.child_tasks",
    "trio.Nursery.parent_task",
    "trio.Nursery.start",
    "trio.Nursery.start_soon",
    "trio.Path",
    "trio.Path.absolute",
    "trio.Path.as_posix",
    "trio.Path.as_uri",
    "trio.Path.chmod",
    "trio.Path.cwd",
    "trio.Path.exists",
    "trio.Path.expanduser",
    "trio.Path.glob",
    "trio.Path.group",
    "trio.Path.hardlink_to",
    "trio.Path.home",
    "trio.Path.is_absolute",
    "trio.Path.is_block_device",
    "trio.Path.is_char_device",
    "trio.Path.is_dir",
    "trio.Path.is_fifo",
    "trio.Path.is_file",
    "trio.Path.is_mount",
    "trio.Path.is_relative_to",
    "trio.Path.is_reserved",
    "trio.Path.is_socket",
    "trio.Path.is_symlink",
    "trio.Path.iterdir",
    "trio.Path.joinpath",
    "trio.Path.lchmod",
    "trio.Path.link_to",
    "trio.Path.lstat",
    "trio.Path.match",
    "trio.Path.mkdir",
    "trio.Path.open",
    "trio.Path.owner",
    "trio.Path.read_bytes",
    "trio.Path.read_text",
    "trio.Path.readlink",
    "trio.Path.relative_to",
    "trio.Path.rename",
    "trio.Path.replace",
    "trio.Path.resolve",
    "trio.Path.rglob",
    "trio.Path.rmdir",
    "trio.Path.samefile",
    "trio.Path.stat",
    "trio.Path.symlink_to",
    "trio.Path.touch",
    "trio.Path.unlink",
    "trio.Path.with_name",
    "trio.Path.with_stem",
    "trio.Path.with_suffix",
    "trio.Path.write_bytes",
    "trio.Path.write_text",
    "trio.Process",
    "trio.Process.aclose",
    "trio.Process.kill",
    "trio.Process.poll",
    "trio.Process.returncode",
    "trio.Process.send_signal",
    "trio.Process.terminate",
    "trio.Process.wait",
    "trio.SSLListener",
    "trio.SSLListener.accept",
    "trio.SSLListener.aclose",
    "trio.SSLStream",
    "trio.SSLStream.aclose",
    "trio.SSLStream.do_handshake",
    "trio.SSLStream.receive_some",
    "trio.SSLStream.send_all",
    "trio.SSLStream.unwrap",
    "trio.SSLStream.wait_send_all_might_not_block",
    "trio.Semaphore",
    "trio.Semaphore.acquire",
    "trio.Semaphore.acquire_nowait",
    "trio.Semaphore.max_value",
    "trio.Semaphore.release",
    "trio.Semaphore.statistics",
    "trio.Semaphore.value",
    "trio.SocketListener",
    "trio.SocketListener.accept",
    "trio.SocketListener.aclose",
    "trio.SocketStream",
    "trio.SocketStream.aclose",
    "trio.SocketStream.getsockopt",
    "trio.SocketStream.receive_some",
    "trio.SocketStream.send_all",
    "trio.SocketStream.send_eof",
    "trio.SocketStream.setsockopt",
    "trio.SocketStream.wait_send_all_might_not_block",
    "trio.StapledStream",
    "trio.StapledStream.aclose",
    "trio.StapledStream.receive_some",
    "trio.StapledStream.send_all",
    "trio.StapledStream.send_eof",
    "trio.StapledStream.wait_send_all_might_not_block",
    "trio.StrictFIFOLock",
    "trio.StrictFIFOLock.acquire",
    "trio.StrictFIFOLock.acquire_nowait",
    "trio.StrictFIFOLock.locked",
    "trio.StrictFIFOLock.release",
    "trio.StrictFIFOLock.statistics",
    "trio.abc.AsyncResource",
    "trio.abc.AsyncResource.aclose",
    "trio.abc.Channel",
    "trio.abc.Channel.aclose",
    "trio.abc.Clock",
    "trio.abc.Clock.current_time",
    "trio.abc.Clock.deadline_to_sleep_time",
    "trio.abc.Clock.start_clock",
    "trio.abc.HalfCloseableStream",
    "trio.abc.HalfCloseableStream.aclose",
    "trio.abc.HalfCloseableStream.receive_some",
    "trio.abc.HalfCloseableStream.send_all",
    "trio.abc.HalfCloseableStream.send_eof",
    "trio.abc.HalfCloseableStream.wait_send_all_might_not_block",
    "trio.abc.HostnameResolver",
    "trio.abc.HostnameResolver.getaddrinfo",
    "trio.abc.HostnameResolver.getnameinfo",
    "trio.abc.Instrument",
    "trio.abc.Instrument.after_io_wait",
    "trio.abc.Instrument.after_run",
    "trio.abc.Instrument.after_task_step",
    "trio.abc.Instrument.before_io_wait",
    "trio.abc.Instrument.before_run",
    "trio.abc.Instrument.before_task_step",
    "trio.abc.Instrument.task_exited",
    "trio.abc.Instrument.task_scheduled",
    "trio.abc.Instrument.task_spawned",
    "trio.abc.Listener",
    "trio.abc.Listener.accept",
    "trio.abc.Listener.aclose",
    "trio.abc.ReceiveChannel",
    "trio.abc.ReceiveChannel.aclose",
    "trio.abc.ReceiveStream",
    "trio.abc.ReceiveStream.aclose",
    "trio.abc.ReceiveStream.receive_some",
    "trio.abc.SendChannel",
    "trio.abc.SendChannel.aclose",
    "trio.abc.SendStream",
    "trio.abc.SendStream.aclose",
    "trio.abc.SendStream.send_all",
    "trio.abc.SendStream.wait_send_all_might_not_block",
    "trio.abc.SocketFactory",
    "trio.abc.SocketFactory.socket",
    "trio.abc.Stream",
    "trio.abc.Stream.aclose",
    "trio.abc.Stream.receive_some",
    "trio.abc.Stream.send_all",
    "trio.abc.Stream.wait_send_all_might_not_block",
    "trio.aclose_forcefully",
    "trio.current_effective_deadline",
    "trio.current_time",
    "trio.fail_after",
    "trio.fail_at",
    "trio.from_thread.run",
    "trio.from_thread.run_sync",
    "trio.lowlevel.FdStream",
    "trio.lowlevel.ParkingLot",
    "trio.lowlevel.ParkingLot.park",
    "trio.lowlevel.ParkingLot.repark",
    "trio.lowlevel.ParkingLot.repark_all",
    "trio.lowlevel.ParkingLot.statistics",
    "trio.lowlevel.ParkingLot.unpark",
    "trio.lowlevel.ParkingLot.unpark_all",
    "trio.lowlevel.RaiseCancelT",
    "trio.lowlevel.RunVar",
    "trio.lowlevel.RunVar.get",
    "trio.lowlevel.RunVar.reset",
    "trio.lowlevel.RunVar.set",
    "trio.lowlevel.Task.child_nurseries",
    "trio.lowlevel.Task.eventual_parent_nursery",
    "trio.lowlevel.Task.iter_await_frames",
    "trio.lowlevel.Task.parent_nursery",
    "trio.lowlevel.TrioToken",
    "trio.lowlevel.TrioToken.run_sync_soon",
    "trio.lowlevel.UnboundedQueue",
    "trio.lowlevel.UnboundedQueue.empty",
    "trio.lowlevel.UnboundedQueue.get_batch",
    "trio.lowlevel.UnboundedQueue.get_batch_nowait",
    "trio.lowlevel.UnboundedQueue.put_nowait",
    "trio.lowlevel.UnboundedQueue.qsize",
    "trio.lowlevel.UnboundedQueue.statistics",
    "trio.lowlevel.cancel_shielded_checkpoint",
    "trio.lowlevel.checkpoint",
    "trio.lowlevel.checkpoint_if_cancelled",
    "trio.lowlevel.current_clock",
    "trio.lowlevel.current_root_task",
    "trio.lowlevel.current_statistics",
    "trio.lowlevel.current_task",
    "trio.lowlevel.current_trio_token",
    "trio.lowlevel.currently_ki_protected",
    "trio.lowlevel.disable_ki_protection",
    "trio.lowlevel.enable_ki_protection",
    "trio.lowlevel.notify_closing",
    "trio.lowlevel.permanently_detach_coroutine_object",
    "trio.lowlevel.reattach_detached_coroutine_object",
    "trio.lowlevel.reschedule",
    "trio.lowlevel.spawn_system_task",
    "trio.lowlevel.temporarily_detach_coroutine_object",
    "trio.lowlevel.wait_readable",
    "trio.lowlevel.wait_writable",
    "trio.move_on_after",
    "trio.move_on_at",
    "trio.open_file",
    "trio.open_nursery",
    "trio.open_signal_receiver",
    "trio.open_ssl_over_tcp_listeners",
    "trio.open_ssl_over_tcp_stream",
    "trio.open_tcp_listeners",
    "trio.open_tcp_stream",
    "trio.open_unix_socket",
    "trio.run_process",
    "trio.serve_listeners",
    "trio.serve_ssl_over_tcp",
    "trio.serve_tcp",
    "trio.sleep",
    "trio.sleep_forever",
    "trio.sleep_until",
    "trio.socket.from_stdlib_socket",
    "trio.socket.fromfd",
    "trio.socket.getaddrinfo",
    "trio.socket.getnameinfo",
    "trio.socket.getprotobyname",
    "trio.socket.set_custom_hostname_resolver",
    "trio.socket.set_custom_socket_factory",
    "trio.socket.socket",
    "trio.socket.socketpair",
    "trio.testing.MemoryReceiveStream",
    "trio.testing.MemoryReceiveStream.aclose",
    "trio.testing.MemoryReceiveStream.close",
    "trio.testing.MemoryReceiveStream.put_data",
    "trio.testing.MemoryReceiveStream.put_eof",
    "trio.testing.MemoryReceiveStream.receive_some",
    "trio.testing.MemorySendStream",
    "trio.testing.MemorySendStream.aclose",
    "trio.testing.MemorySendStream.close",
    "trio.testing.MemorySendStream.get_data",
    "trio.testing.MemorySendStream.get_data_nowait",
    "trio.testing.MemorySendStream.send_all",
    "trio.testing.MemorySendStream.wait_send_all_might_not_block",
    "trio.testing.MockClock",
    "trio.testing.MockClock.autojump_threshold",
    "trio.testing.MockClock.current_time",
    "trio.testing.MockClock.deadline_to_sleep_time",
    "trio.testing.MockClock.jump",
    "trio.testing.MockClock.rate",
    "trio.testing.MockClock.start_clock",
    "trio.testing.assert_checkpoints",
    "trio.testing.assert_no_checkpoints",
    "trio.testing.check_half_closeable_stream",
    "trio.testing.check_one_way_stream",
    "trio.testing.check_two_way_stream",
    "trio.testing.lockstep_stream_one_way_pair",
    "trio.testing.lockstep_stream_pair",
    "trio.testing.memory_stream_one_way_pair",
    "trio.testing.memory_stream_pair",
    "trio.testing.memory_stream_pump",
    "trio.testing.open_stream_to_socket_listener",
    "trio.testing.trio_test",
    "trio.testing.wait_all_tasks_blocked",
    "trio.to_thread.current_default_thread_limiter",
    "trio.wrap_file",
}


# don't require annotations for objects inherited without modification from a builtin class
# mainly for Exception `.attr` and `.with_traceback`
def is_in_builtin_superclass(
    name: str, value: object, superclasses: list[type]
) -> bool:
    for superclass in superclasses:
        if hasattr(superclass, name) and value == getattr(superclass, name):
            return True
    return False


# note that this does not check if an export is *fully* annotated, that's left for mypy
@pytest.mark.skipif(
    sys.version_info < (3, 10), reason="no inspect.get_annotations() in <3.10"
)
def test_public_exports_typed(tmp_path: Path) -> None:
    # read yaml file with reveal_type tests to get which objects are tested
    yaml_test_file = Path(__file__).parent / "test_all_public_types.yml"
    with open(yaml_test_file) as f:
        yaml_tested = yaml.safe_load(f)
    assert isinstance(yaml_tested, list)
    assert isinstance(yaml_tested[0], dict)
    assert "main" in yaml_tested[0]

    # names of objects tested in the yaml, should have no overlap with HAS_NO_ANNOTATION
    tested: set[str] = set(
        re.findall(r"(?<=reveal_type\().*?(?=\))", yaml_tested[0]["main"])
    )
    # filled with all names as they're checked, should equal tested|HAS_NO_ANNOTATION
    checked_names: set[str] = set()

    # these three sets should be empty on a succesful test
    has_annotation_not_in_tested: set[str] = set()
    no_anno_not_marked: set[str] = set()
    anno_marked: set[str] = set()

    # functions defined inside to not have to pass around the above sets
    def check_name_is_annotated(
        name: str, obj: Any, override_has_anno: bool | None = None
    ) -> None:
        assert name not in checked_names
        checked_names.add(name)
        try:
            has_anno = bool(inspect.get_annotations(obj))
        except TypeError:
            has_anno = True
        if override_has_anno is not None:
            has_anno = override_has_anno
        if has_anno:
            if name in HAS_NO_ANNOTATION:
                anno_marked.add(name)
            if name not in tested:
                has_annotation_not_in_tested.add(name)
        else:
            assert name not in tested, "export lacking annotation is tested"
            if name not in HAS_NO_ANNOTATION:
                no_anno_not_marked.add(name)

    def check_class(full_name: str, obj: type) -> None:
        # skip enums, which also can't really be annotated
        if isinstance(obj, enum.EnumMeta):
            return

        superclasses = list(
            filter(lambda x: hasattr(builtins, x.__name__), obj.__mro__)
        )
        has_any_attrs = False

        for mname, mobj in inspect.getmembers(obj):
            # ignore dunder and private objects (for now?)
            if mname.startswith("_"):
                continue

            # mainly for Exception `.attr` and `.with_traceback`
            if is_in_builtin_superclass(mname, mobj, superclasses):
                continue

            has_any_attrs = True
            full_attr_name = f"{full_name}.{mname}"

            if inspect.isgetsetdescriptor(mobj) or inspect.ismemberdescriptor(mobj):
                # attributes set with attrs
                # handled by getting annotation for the class itself
                continue
            if isinstance(mobj, property):
                has_anno = False
                for _, mm in inspect.getmembers(mobj, inspect.isfunction):
                    if inspect.get_annotations(mm):
                        has_anno = True
                        break
                check_name_is_annotated(
                    full_attr_name, mobj, override_has_anno=has_anno
                )
                continue
            check_name_is_annotated(full_attr_name, mobj)

        if has_any_attrs:
            check_name_is_annotated(full_name, obj)

    # traverse all public modules for public objects, checking that they're annotated
    for module in PUBLIC_MODULES:
        for name, obj in inspect.getmembers(module):
            if inspect.isbuiltin(obj) or name.startswith("_") or inspect.ismodule(obj):
                continue

            full_name = f"{module.__name__}.{name}"

            if inspect.isclass(obj):
                check_class(full_name, obj)
            elif callable(obj):
                check_name_is_annotated(full_name, obj)
            else:
                # ignore re-exported objects from socket
                if module == trio.socket and name in dir(socket):
                    continue
                # get_annotations does not work for non-class/callables, so require
                # them in the test file
                check_name_is_annotated(full_name, obj, override_has_anno=True)

    # pretty-print missing/extra lines for ease of copy-paste

    # objects with annotation not in the yaml test file
    if has_annotation_not_in_tested:
        import mypy
        from mypy.api import run

        # mypy does not like long strings passed with `-c`, so write to a file
        tmp_file = tmp_path / "reveal_types.py"
        tmp_file.write_text(
            "import trio\n"
            + "\n".join(
                f"reveal_type({name})" for name in sorted(has_annotation_not_in_tested)
            )
        )
        res = run([str(tmp_file)])
        revealed_types = re.findall(r'(?<=Revealed type is ").*?(?=")', res[0])

        print("\nFollowing lines are missing in {yaml_test_file.name}")
        for name, revealed_type in zip(
            sorted(has_annotation_not_in_tested), revealed_types, strict=True
        ):
            print(f'    reveal_type({name})  # N: Revealed type is "{revealed_type}"')

    if no_anno_not_marked:
        print(
            "\nFollowing unannotated exports are not marked in HAS_NO_ANNOTATION,"
            " please add them in {__file__}"
        )
        pprint(no_anno_not_marked)

    if anno_marked:
        print(
            "\nFollowing annotated exports are marked in HAS_NO_ANNOTATION,"
            " please remove them in {__file__}"
        )
        pprint(anno_marked)

    # asserts for the above print checks
    assert (
        not has_annotation_not_in_tested
    ), f"objects missing from {yaml_test_file.name}"
    assert (
        not no_anno_not_marked
    ), "objects lacking annotation not marked in HAS_NO_ANNOTATIONS"
    assert not anno_marked, "objects with annotation marked in HAS_NO_ANNOTATIONS"

    # moar asserts
    assert (
        HAS_NO_ANNOTATION - checked_names == set()
    ), "unchecked or nonexistent objects in HAS_NO_ANNOTATIONS"
    assert (
        tested - checked_names == set()
    ), "object listed in {yaml_test_file} never traversed in the checker. Move to different test file or fix the checker."
    assert tested & HAS_NO_ANNOTATION == set()
