from __future__ import annotations
import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict

logger = logging.getLogger(__name__)

class MainUI(ttk.Frame):
    """Tkinter-based minimal UI to drive the simulation."""
    def __init__(self, master: tk.Tk, controller, bus, data_adapter, tick_ms: int = 100):
        super().__init__(master)
        self.master = master
        self.controller = controller
        self.bus = bus
        self.data_adapter = data_adapter
        self.tick_ms = tick_ms
        self._loop_running = False
        self._build()
        self._wire_events()

    def _build(self) -> None:
        self.master.title('RTD_SIM — Cognitive ABM Demo')
        self.pack(fill='both', expand=True)

        toolbar = ttk.Frame(self)
        toolbar.pack(side='top', fill='x', padx=8, pady=8)

        self.start_btn = ttk.Button(toolbar, text='Start', command=self.on_start)
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(toolbar, text='Stop', command=self.on_stop)
        self.stop_btn.pack(side='left', padx=4)
        self.reset_btn = ttk.Button(toolbar, text='Reset', command=self.on_reset)
        self.reset_btn.pack(side='left', padx=4)

        self.status = tk.StringVar(value='Ready')
        ttk.Label(toolbar, textvariable=self.status).pack(side='right')

        self.tree = ttk.Treeview(self, columns=('attention','working_memory','stress','performance'), show='headings', height=12)
        for col in self.tree['columns']:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor='center')
        self.tree.pack(fill='both', expand=True, padx=8, pady=8)

        self.log = tk.Text(self, height=6)
        self.log.pack(fill='both', expand=False, padx=8, pady=8)

    def _wire_events(self) -> None:
        self.bus.subscribe('sim_started', lambda: self._set_status('Running'))
        self.bus.subscribe('sim_stopped', lambda step: self._set_status(f'Stopped @ {step}'))
        self.bus.subscribe('sim_reset', lambda: self._set_status('Reset'))
        self.bus.subscribe('state_updated', self.on_state_updated)
        self.bus.subscribe('log_entry', self.on_log_entry)

    def _set_status(self, txt: str) -> None:
        self.status.set(txt)

    def on_start(self) -> None:
        self.controller.start()
        if not self._loop_running:
            self._loop_running = True
            self._loop()

    def on_stop(self) -> None:
        self.controller.stop()
        self._loop_running = False

    def on_reset(self) -> None:
        self.controller.reset()
        self.tree.delete(*self.tree.get_children())
        self.log.delete('1.0', 'end')

    def _loop(self) -> None:
        if self._loop_running:
            self.controller.step()
            self.master.after(self.tick_ms, self._loop)

    def on_state_updated(self, step: int, state: Dict[str, Any]) -> None:
        self.data_adapter.append_log(step, state)
        values = (state['attention'], state['working_memory'], state['stress'], state['performance'])
        self.tree.insert('', 'end', values=values)
        rows = self.tree.get_children()
        if len(rows) > 200:
            self.tree.delete(rows[0])

    def on_log_entry(self, message: str) -> None:
        self.log.insert('end', message + '\n')
        self.log.see('end')