import os
from os import path

import psutil
from typing import NamedTuple, List, Dict, Set, Tuple
import re
import argparse
import time
import csv

_timer = getattr(time, 'monotonic', time.time)

class SystemUsageRecord(NamedTuple):
    time: float
    cpu: float
    cpu_user: float
    cpu_system: float
    cpu_idle: float
    cpu_iowait: float
    cpu_count: int
    mem_total: float
    mem_available: float
    mem_used: float


class ProcessRecord(NamedTuple):
    time: float
    pid: int
    parent_pid: int
    upid: int
    parent_upid: int
    name: str
    args: List[str]
    create_time: float
    p_impl: psutil.Process
    last_sys_time: float = []
    last_thread_proc_times: Dict[int, Tuple] = None


class PerformanceRecord(NamedTuple):
    time: float
    pid: int
    upid: int
    cpu_percent: float
    memory_rss: int
    num_mmaps: int
    num_threads: int
    

class PerformanceThreadRecord(NamedTuple):
    time: float
    pid: int
    upid: int
    tid: int
    name: str
    cpu_percent: float


class Monitor:    
    _current_processes: Dict[int, ProcessRecord]

    def __init__(self, search_regex: str, pinfo_writer, pperf_writer, tperf_writer, system_writer):
        self._current_processes = dict()
        self._search_regex = re.compile(search_regex)
        self._num_cpus = psutil.cpu_count()
        self._pinfo_writer = pinfo_writer
        self._pperf_writer = pperf_writer
        self._tperf_writer = tperf_writer
        self._system_writer = system_writer
        self._upid_counter = 0
        self._pid2upid = {}

    def timer(self):
        return _timer() * self._num_cpus
         
    def monitor(self):
        self._write_system_stats()

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
                self._upid_counter += 1
                upid = self._upid_counter
                self._pid2upid[pid] = upid
                parent_upid = self._pid2upid.get(p.info['ppid'])
                
                pr = ProcessRecord(
                    pid=pid,
                    upid=upid,
                    parent_pid=p.info['ppid'],
                    parent_upid=parent_upid,
                    name=p.info['name'],
                    args=p.info['cmdline'],
                    create_time=p.info['create_time'],
                    p_impl=p,
                    last_sys_time=[self.timer()],
                    last_thread_proc_times=dict(),
                    time=time.time(),
                )
                self._current_processes[pid] = pr
                r = pr._asdict()
                del r['p_impl']
                self._pinfo_writer.writerow(r)

        to_delete = set(self._current_processes.keys()) - current
        for pid in to_delete:
            del self._current_processes[pid]
            del self._pid2upid[pid]


        for pr in self._current_processes.values():
            p = pr.p_impl
            with p.oneshot():
                cpu_percent = p.cpu_percent()
                memory_info = p.memory_info()
                num_threads = p.num_threads()
                memory_rss = memory_info.rss
                maps = p.memory_maps(grouped=False)
                num_mmaps = len(maps)

                threads = p.threads()
                # print(th)
                perf_record = PerformanceRecord(
                    pid=pr.pid,
                    upid=self._pid2upid.get(pr.pid),
                    cpu_percent=cpu_percent,
                    memory_rss=memory_rss,
                    num_mmaps=num_mmaps,
                    num_threads=num_threads,
                    time=time.time(),
                    )
                sys_time = self.timer() 
                last_sys_time =  pr.last_sys_time[0]   
                for t in threads:
                    total_time = t.user_time + t.system_time
                    last_total_time = pr.last_thread_proc_times.get(t.id)
                    
                    if last_total_time is None:
                        cpu_percent = 0.0
                    else:
                        delta = total_time - last_total_time
                        delta_sys = sys_time - last_sys_time
                        cpu_percent = delta / delta_sys * 100.0
                    cpu_percent = cpu_percent * self._num_cpus
                    cpu_percent = round(cpu_percent, 1)
                    
                    pr.last_thread_proc_times[t.id] = total_time
                    upid = self._pid2upid.get(pr.pid)
                    tr = PerformanceThreadRecord(pid=pr.pid, upid=upid, tid=t.id, name=t.name, cpu_percent=cpu_percent, time=time.time(),)
                    self._tperf_writer.writerow(tr._asdict())
                self._pperf_writer.writerow(perf_record._asdict())
                # print(perf_record)
                pr.last_sys_time[0] = sys_time

    def _write_system_stats(self):
        cpu_percent = psutil.cpu_percent()
        cpu_count = psutil.cpu_count()

        cpu_times_percent = psutil.cpu_times_percent()
        virtual_memory = psutil.virtual_memory()
        sys_record = SystemUsageRecord(
            time=time.time(),
            cpu=cpu_percent,
            cpu_count=cpu_count,
            cpu_system=cpu_times_percent.system,
            cpu_user=cpu_times_percent.user,
            cpu_idle=cpu_times_percent.idle,
            cpu_iowait=getattr(cpu_times_percent, 'iowait', None),
            mem_total=virtual_memory.total,
            mem_used=virtual_memory.used,
            mem_available=virtual_memory.available,
        )

        self._system_writer.writerow(sys_record._asdict())


p = argparse.ArgumentParser()
p.add_argument('-o', '--output', required=True)
p.add_argument('-r', '--pattern', required=True)
p.add_argument('--interval', default=2, type=int)
p.add_argument('--append', action='store_true')

args = p.parse_args()

mode = 'a' if args.append else 'w'

os.makedirs(args.output, exist_ok=True)

info_file = path.join(args.output, 'info.txt')
proc_file = path.join(args.output, 'proc.txt')
thread_file = path.join(args.output, 'thread.txt')
system_file = path.join(args.output, 'system.txt')


with open(info_file, mode) as finfo, \
    open(proc_file, mode) as fproc, \
    open(thread_file, mode) as fthread, \
    open(system_file, mode) as fsystem:
    info_writer = csv.DictWriter(finfo, ProcessRecord._fields, delimiter='\t')
    pproc_writer = csv.DictWriter(fproc, PerformanceRecord._fields, delimiter='\t')
    tproc_writer = csv.DictWriter(fthread, PerformanceThreadRecord._fields, delimiter='\t')
    system_writer = csv.DictWriter(fsystem, SystemUsageRecord._fields, delimiter='\t')

    if not args.append:
        info_writer.writeheader()
        pproc_writer.writeheader()
        tproc_writer.writeheader()
        system_writer.writeheader()

    m = Monitor(args.pattern, info_writer, pproc_writer, tproc_writer, system_writer)
    
    while True:
        try:
            m.monitor()
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break
        except Exception as ex:
            print(ex)
        
        


        