import psutil
from typing import NamedTuple, List, Dict, Set
import re


class ProcessRecord(NamedTuple):
    pid: int
    parent_pid: int
    name: str
    args: List[str]
    create_time: float


class PerformanceRecord(NamedTuple):
    pid: int
    # thread_name: int = None
    cpu_percent: float
    memory_rss: int
    num_mmaps: int
    num_threads: int
    

class PerformanceThreadRecord(NamedTuple):
    pid: int
    name: str
    # cpu_percent: float


class Monitor:    
    _current_processes: Dict[int, ProcessRecord]

    def __init__(self, search_regex: str):
        self._current_processes = dict()
        self._search_regex = re.compile(search_regex)

    def monitor(self):
        # Update Processes
        current: Set[int] = set()

        for p in psutil.process_iter(attrs=['pid', 'name', 'ppid', 'cmdline', 'create_time']):
            # print(' '.join(p.info['cmdline'] or []))
            if not self._search_regex.match(p.info['name']) and \
                not self._search_regex.match(' '.join(p.info['cmdline'] or [])):
                continue

            pid = p.info['pid']
            current.add(pid)
            if pid not in self._current_processes:
                pr = ProcessRecord(
                    pid=pid,
                    parent_pid=p.info['ppid'],
                    name=p.info['name'],
                    args=p.info['cmdline'],
                    create_time=p.info['create_time'],
                )
                self._current_processes[pid] = pr
                print(pr)

        to_delete = set(self._current_processes.keys()) - current
        for pid in to_delete:
            del self._current_processes[pid]


        for pr in self._current_processes.values():
            p = psutil.Process(pr.pid)
            with p.oneshot():
                cpu_percent = p.cpu_percent()
                memory_info = p.memory_info()
                num_threads = p.num_threads()
                memory_rss = memory_info.rss
                maps = p.memory_maps(grouped=False)
                num_mmaps = len(maps)

                th = p.threads()
                print(th)
                perf_record = PerformanceRecord(
                    pid=pr.pid,
                    cpu_percent=cpu_percent,
                    memory_rss=memory_rss,
                    num_mmaps=num_mmaps,
                    num_threads=num_threads,
                    )
                print(perf_record)


m = Monitor(".*MaxQuantTask.*")
m.monitor()