from colorama import Fore
import pyfiglet, random

class Banner:
    def __init__(self, display_text):
        self.display_text = display_text
        self.lg = Fore.LIGHTGREEN_EX
        self.w = Fore.WHITE
        self.cy = Fore.CYAN
        self.ye = Fore.YELLOW
        self.r = Fore.RED
        self.n = Fore.RESET

    def print_banner(self):
        colors = [self.lg, self.r, self.w, self.cy, self.ye]
        f = pyfiglet.Figlet(font='slant')
        display_text = f.renderText(self.display_text)
        color = random.choice(colors)
        print(f'{color}{display_text}{self.n}')
        print(f'{color}  Version: v0.0.1 \n{self.n}')
        # print(f'{color}  Version: v0.0.1 \nby: paulovisam\n{self.n}')