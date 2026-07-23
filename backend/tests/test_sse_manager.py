"""SseManager 单元测试"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sse_manager import sse_manager


def _start_gen(gen):
    """启动异步生成器直到其阻塞在 queue.get()，然后返回."""
    results = []

    async def _run():
        try:
            msg = await asyncio.wait_for(gen.__anext__(), timeout=3)
            results.append(msg)
        except asyncio.TimeoutError:
            pass  # no event pushed yet, that's expected

    task = asyncio.create_task(_run())
    return task, results


async def test_subscribe_and_push():
    """subscribe → start generator → push → consume"""
    run_id = "test_qa_1"
    gen = sse_manager.subscribe(run_id)

    # start generator (this creates the queue internally)
    task, results = _start_gen(gen)
    await asyncio.sleep(0.05)

    # push event
    await sse_manager.push(run_id, "step_update", {
        "type": "step_update", "status": "running"
    })

    await task
    msg = results[0]
    assert "event: step_update" in msg
    assert '"status": "running"' in msg
    print("[PASS] T1.1a: subscribe + push + consume")

    sse_manager.disconnect(run_id)


async def test_push_without_subscriber():
    """push with no subscriber — should not raise"""
    await sse_manager.push("test_no_sub", "x", {"a": 1})
    print("[PASS] T1.1b: push without subscriber OK")


async def test_disconnect():
    """disconnect cleans up queues & clients"""
    run_id = "test_dc"
    gen = sse_manager.subscribe(run_id)

    # start generator first
    task, _ = _start_gen(gen)
    await asyncio.sleep(0.05)

    assert run_id in sse_manager._queues
    assert run_id in sse_manager._clients

    sse_manager.disconnect(run_id)
    assert run_id not in sse_manager._queues
    assert run_id not in sse_manager._clients
    print("[PASS] T1.1c: disconnect cleanup")

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


async def test_multiple_events():
    """multiple events in sequence"""
    run_id = "test_multi"
    gen = sse_manager.subscribe(run_id)

    results = []

    async def consumer():
        for _ in range(3):
            msg = await asyncio.wait_for(gen.__anext__(), timeout=3)
            results.append(msg)

    ctask = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)

    await sse_manager.push(run_id, "step_update", {"type": "step_update", "step": 1})
    await sse_manager.push(run_id, "step_completed", {"type": "step_completed", "step": 1})
    await sse_manager.push(run_id, "run_completed", {"type": "run_completed"})

    await ctask
    assert "step_update" in results[0]
    assert "step_completed" in results[1]
    assert "run_completed" in results[2]
    print("[PASS] T1.1d: multiple events in sequence")

    sse_manager.disconnect(run_id)


async def test_json_serialization():
    """JSON serialization with unicode characters"""
    run_id = "test_json"
    gen = sse_manager.subscribe(run_id)

    results = []

    async def consumer():
        msg = await asyncio.wait_for(gen.__anext__(), timeout=3)
        results.append(msg)

    ctask = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)

    await sse_manager.push(run_id, "step_update", {
        "type": "step_update",
        "agent": "分诊Agent",
        "output": "检测到异常行为",
    })

    await ctask
    msg = results[0]
    assert "分诊Agent" in msg or "\\u5206\\u8b" in msg
    print("[PASS] T1.1e: JSON serialization with unicode")

    sse_manager.disconnect(run_id)


async def test_queue_full_behavior():
    """Queue full should not block push indefinitely (5s timeout)"""
    run_id = "test_full"
    # 创建一个容量为 1 的队列
    from app.services.sse_manager import SseManager
    mgr = SseManager()
    mgr._queues[run_id] = asyncio.Queue(maxsize=1)
    mgr._clients[run_id] = set()

    # 填满队列
    await mgr._queues[run_id].put(("evt", {"x": 1}))

    # 再 push 应该超时但不抛异常
    await mgr.push(run_id, "evt2", {"x": 2})
    print("[PASS] T1.1f: queue full handling (timeout, event dropped)")


async def main():
    print("=" * 60)
    print("SseManager 单元测试")
    print("=" * 60)

    tests = [
        ("subscribe + push + consume", test_subscribe_and_push),
        ("push without subscriber", test_push_without_subscriber),
        ("disconnect cleanup", test_disconnect),
        ("multiple events", test_multiple_events),
        ("JSON serialization", test_json_serialization),
        ("queue full handling", test_queue_full_behavior),
    ]

    passed = 0
    failed = 0

    for name, test in tests:
        try:
            await test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n结果: {passed}/{passed + failed} 通过")
    return passed, failed


if __name__ == "__main__":
    p, f = asyncio.run(main())
    sys.exit(1 if f > 0 else 0)
