import subprocess
import threading
import atexit
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.ticker import FormatStrFormatter, FuncFormatter
import matplotlib.ticker as ticker

LOG_FILE = "battery_data.csv"
LOAD_RESISTANCE = 1.0


class SmartBatteryMonitor:
    def __init__(self):

        self.time_buffer = []
        self.data_buffer = []


        self.online_x = []
        self.online_y = []
        self.offline_x = []
        self.offline_y = []

        self.lock = threading.Lock()
        self.is_connected = False
        self.is_finished = False

        self.last_time = None
        self.last_val = None
        self.total_energy_wh = 0.0
        self.ignore_until = 0
        self.process = None


        self.file_handle = open(LOG_FILE, "w")

        self.file_handle.write("Time_sec,Voltage_V,Energy_Wh\n")
        self.file_handle.flush()

        atexit.register(self.cleanup)

    def cleanup(self):
        if self.process:
            self.process.terminate()
        if self.file_handle and not self.file_handle.closed:
            self.file_handle.close()

    def read_from_c(self):
        try:
            self.process = subprocess.Popen(['reader.exe', 'COM11'], stdout=subprocess.PIPE, text=True)
        except FileNotFoundError:
            return

        sync_buffer = []
        start_time = None

        while True:
            line = self.process.stdout.readline().strip()
            if not line:
                continue

            if line == "ERR":
                with self.lock:
                    self.is_connected = False
                continue

            try:
                parts = line.split(',')
                if len(parts) != 2:
                    continue

                status = parts[0]
                v_val = float(parts[1])

                with self.lock:
                    if self.is_finished:
                        continue

                    if start_time is None and status == "ONLINE":
                        start_time = time.time()
                        t_sec = 0.0
                    elif start_time is not None:
                        t_sec = time.time() - start_time
                    else:
                        continue

                    if status == "OFFLINE":
                        sync_buffer.append(v_val)
                        continue

                    elif status == "ONLINE":
                        if len(sync_buffer) > 0:
                            self.is_connected = True
                            self.ignore_until = t_sec + 3.0

                            if self.last_time is not None:
                                dt = t_sec - self.last_time
                                step = dt / (len(sync_buffer) + 1)
                                dynamic_offset = self.last_val - sync_buffer[0]

                                for i, sync_val in enumerate(sync_buffer):
                                    if self.is_finished:
                                        break

                                    restored_time = self.last_time + step * (i + 1)
                                    corrected_val = sync_val + dynamic_offset

                                    if corrected_val <= 0.505:
                                        corrected_val = 0.50
                                        self.is_finished = True

                                    avg_v = (corrected_val + self.last_val) / 2.0
                                    p_watts = (avg_v ** 2) / LOAD_RESISTANCE
                                    self.total_energy_wh += p_watts * (step / 3600.0)

                                    self.time_buffer.append(restored_time)
                                    self.data_buffer.append(corrected_val)
                                    self.offline_x.append(restored_time)
                                    self.offline_y.append(corrected_val)

                                    self.file_handle.write(
                                        f"{restored_time:.2f},{corrected_val:.2f},{self.total_energy_wh:.6f}\n")
                                    self.last_val = corrected_val

                            sync_buffer.clear()
                            self.file_handle.flush()
                            continue

                        if not self.is_connected:
                            self.is_connected = True
                            self.ignore_until = t_sec + 3.0
                            continue

                        if t_sec < self.ignore_until:
                            continue

                        if v_val <= 0.505:
                            v_val = 0.50
                            self.is_finished = True

                        if self.last_time is not None:
                            dt = t_sec - self.last_time
                            if dt > 0:
                                avg_v = (v_val + self.last_val) / 2.0
                                p_watts = (avg_v ** 2) / LOAD_RESISTANCE
                                self.total_energy_wh += p_watts * (dt / 3600.0)

                        self.time_buffer.append(t_sec)
                        self.data_buffer.append(v_val)
                        self.online_x.append(t_sec)
                        self.online_y.append(v_val)

                        self.last_time = t_sec
                        self.last_val = v_val

                        self.file_handle.write(f"{t_sec:.2f},{v_val:.2f},{self.total_energy_wh:.6f}\n")
                        self.file_handle.flush()

            except ValueError:
                pass

    def update_plot(self, frame, ax, info_text):
        with self.lock:
            if not self.time_buffer:
                return self.line_main, self.points_online, self.points_offline, info_text

            x_main = list(self.time_buffer)
            y_main = list(self.data_buffer)
            x_on, y_on = list(self.online_x), list(self.online_y)
            x_off, y_off = list(self.offline_x), list(self.offline_y)

            status = self.is_connected
            is_fin = self.is_finished
            cap_wh = self.total_energy_wh

        self.line_main.set_data(x_main, y_main)
        self.points_online.set_data(x_on, y_on)
        self.points_offline.set_data(x_off, y_off)

        current_max_x = x_main[-1]
        ax.set_xlim(0, current_max_x * 1.02 if current_max_x > 0 else 1)
        ax.set_ylim(0.5, 1.5)

        def time_fmt(x, pos):
            if current_max_x < 120:
                return f"{x:.0f}"
            elif current_max_x < 3600:
                return f"{x / 60:.0f}"
            else:
                return f"{x / 3600:.2f}"

        ax.xaxis.set_major_formatter(FuncFormatter(time_fmt))

        if current_max_x < 120:
            ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        elif current_max_x < 600:
            ax.xaxis.set_major_locator(ticker.MultipleLocator(base=60))
        elif current_max_x < 1800:
            ax.xaxis.set_major_locator(ticker.MultipleLocator(base=300))
        elif current_max_x < 3600:
            ax.xaxis.set_major_locator(ticker.MultipleLocator(base=600))
        else:
            ax.xaxis.set_major_locator(ticker.AutoLocator())

        if current_max_x < 120:
            ax.set_xlabel("Время (секунды)")
        elif current_max_x < 3600:
            ax.set_xlabel("Время (минуты)")
        else:
            ax.set_xlabel("Время (часы)")

        if is_fin:
            info_text.set_text(f" РАЗРЯД ЗАВЕРШЕН \n Энергия: {cap_wh:.3f} Wh \n Напряжение: 0.50 V ")
            info_text.set_color("green")
        elif status:
            info_text.set_text(f"   Энергия: {cap_wh:.3f} Wh \n Напряжение: {y_main[-1]:.2f} V ")
            info_text.set_color("black")
        else:
            info_text.set_text(" ОБРЫВ СВЯЗИ \n Ожидание данных... ")
            info_text.set_color("red")

        return self.line_main, self.points_online, self.points_offline, info_text

    def run(self):
        fig, ax = plt.subplots(figsize=(10, 6))

        self.line_main, = ax.plot([], [], lw=1.5, color='gray', alpha=0.4, zorder=1)
        self.points_online, = ax.plot([], [], linestyle='None', marker='.', color='blue', markersize=7,
                                      label="Онлайн данные", zorder=2)
        self.points_offline, = ax.plot([], [], linestyle='None', marker='.', color='red', markersize=7,
                                       label="Оффлайн (из памяти)", zorder=3)

        ax.legend(loc="lower left", fontsize=10, framealpha=0.9)

        info_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, verticalalignment='top',
                            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='gray', alpha=0.9),
                            fontsize=12, weight='bold')

        ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
        ax.yaxis.set_major_locator(ticker.MultipleLocator(base=0.05))

        threading.Thread(target=self.read_from_c, daemon=True).start()

        ani = animation.FuncAnimation(fig, self.update_plot, fargs=(ax, info_text),
                                      interval=100, blit=False, cache_frame_data=False)

        plt.title("Измерение разряда аккумулятора")
        plt.ylabel("Напряжение (Вольты)")
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    monitor = SmartBatteryMonitor()
    monitor.run()