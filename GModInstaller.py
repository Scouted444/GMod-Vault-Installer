import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import tarfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox


APP_NAME = "GMod Installer"
VERSION = "1.0"


# ============================================================
# SAFE FILESYSTEM HELPERS
# ============================================================

def safe_exists(path):
    try:
        return path.exists()
    except (OSError, PermissionError):
        return False


def safe_is_dir(path):
    try:
        return path.is_dir()
    except (OSError, PermissionError):
        return False


def safe_resolve(path):
    try:
        return path.resolve()
    except (OSError, PermissionError):
        return path


# ============================================================
# STEAM / GMOD DETECTION
# ============================================================

def find_steam_libraries():
    libraries = []

    possible_steam = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "")) / "Steam",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Steam",

        Path("C:/Steam"),
        Path("D:/Steam"),
        Path("E:/Steam"),
        Path("F:/Steam"),
        Path("G:/Steam"),
    ]

    for steam in possible_steam:

        if not safe_is_dir(steam):
            continue

        libraries.append(steam)

        vdf = steam / "steamapps" / "libraryfolders.vdf"

        if not safe_exists(vdf):
            continue

        try:
            text = vdf.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            paths = re.findall(
                r'"path"\s+"([^"]+)"',
                text
            )

            for path in paths:

                try:
                    library = Path(path)

                    if safe_is_dir(library):
                        libraries.append(library)

                except (OSError, PermissionError):
                    continue

        except (OSError, PermissionError):
            continue

    unique = []
    seen = set()

    for path in libraries:

        try:
            key = str(path).lower()

            if key not in seen:
                seen.add(key)
                unique.append(path)

        except Exception:
            continue

    return unique


def find_gmod():
    for steam in find_steam_libraries():

        try:

            gmod = (
                steam
                / "steamapps"
                / "common"
                / "GarrysMod"
                / "garrysmod"
            )

            if safe_is_dir(gmod):
                return gmod

        except (OSError, PermissionError):
            continue

    return None


# ============================================================
# 7-ZIP
# ============================================================

def find_7zip():

    locations = [
        Path(os.environ.get("PROGRAMFILES", "")) /
        "7-Zip" / "7z.exe",

        Path(os.environ.get("PROGRAMFILES(X86)", "")) /
        "7-Zip" / "7z.exe",

        Path("C:/7-Zip/7z.exe"),
    ]

    for location in locations:

        try:

            if location.exists():
                return location

        except (OSError, PermissionError):
            continue

    found = shutil.which("7z")

    if found:
        return Path(found)

    found = shutil.which("7zz")

    if found:
        return Path(found)

    return None


# ============================================================
# SAFE EXTRACTION
# ============================================================

def safe_zip_extract(archive, destination):

    destination = safe_resolve(destination)

    for member in archive.infolist():

        target = safe_resolve(
            destination / member.filename
        )

        try:
            target.relative_to(destination)

        except ValueError:

            raise RuntimeError(
                "Unsafe ZIP path detected:\n\n"
                + member.filename
            )

    archive.extractall(destination)


def safe_tar_extract(archive, destination):

    destination = safe_resolve(destination)

    for member in archive.getmembers():

        target = safe_resolve(
            destination / member.name
        )

        try:
            target.relative_to(destination)

        except ValueError:

            raise RuntimeError(
                "Unsafe archive path detected:\n\n"
                + member.name
            )

    archive.extractall(destination)


def extract_archive(source, destination):

    extension = source.suffix.lower()

    # ZIP
    if extension == ".zip":

        with zipfile.ZipFile(
            source,
            "r"
        ) as archive:

            safe_zip_extract(
                archive,
                destination
            )

        return

    # TAR
    if extension in {
        ".tar",
        ".tgz",
        ".gz",
        ".bz2",
        ".xz"
    }:

        try:

            with tarfile.open(
                source,
                "r:*"
            ) as archive:

                safe_tar_extract(
                    archive,
                    destination
                )

            return

        except tarfile.ReadError:
            pass

    # 7Z / RAR
    if extension in {
        ".7z",
        ".rar"
    }:

        seven_zip = find_7zip()

        if not seven_zip:

            raise RuntimeError(
                "7-Zip is required to extract this archive.\n\n"
                "Install 7-Zip and try again."
            )

        result = subprocess.run(
            [
                str(seven_zip),
                "x",
                str(source),
                f"-o{destination}",
                "-y"
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:

            raise RuntimeError(
                "7-Zip failed to extract the archive.\n\n"
                + result.stderr
            )

        return

    raise RuntimeError(
        "Unsupported archive type:\n\n"
        + extension
    )


# ============================================================
# GMOD STRUCTURE DETECTION
# ============================================================

GMOD_FOLDERS = {
    "lua",
    "materials",
    "models",
    "sound",
    "scripts",
    "particles",
    "resource",
    "effects",
    "weapons",
    "entities",
    "gamemodes",
    "maps",
    "addons",
    "data",
    "cfg",
    "dupes",
    "demos",
    "saves",
}


def list_files(folder):

    result = []

    try:

        for item in folder.rglob("*"):

            try:

                if item.is_file():
                    result.append(item)

            except (OSError, PermissionError):
                continue

    except (OSError, PermissionError):
        pass

    return result


def clean_wrapper_folder(folder):

    current = folder

    while True:

        try:
            items = list(current.iterdir())

        except (OSError, PermissionError):
            break

        directories = [
            item
            for item in items
            if item.is_dir()
        ]

        files = [
            item
            for item in items
            if item.is_file()
        ]

        if files:
            break

        if len(directories) != 1:
            break

        child = directories[0]

        if child.name.lower() in GMOD_FOLDERS:
            break

        current = child

    return current


def detect_archive(folder):

    root = clean_wrapper_folder(folder)

    files = list_files(root)

    if not files:

        return {
            "type": "Unknown",
            "root": root,
            "destination": None,
        }

    top_folders = set()

    for file in files:

        try:

            relative = file.relative_to(root)

            if relative.parts:
                top_folders.add(
                    relative.parts[0].lower()
                )

        except ValueError:
            pass

    # Existing GMod folder
    if "addons" in top_folders:

        return {
            "type": "GMod Folder",
            "root": root,
            "destination": None,
        }

    # Maps
    if any(
        file.suffix.lower() == ".bsp"
        for file in files
    ):

        return {
            "type": "Map",
            "root": root,
            "destination": "maps",
        }

    # Demos
    if any(
        file.suffix.lower() == ".dem"
        for file in files
    ):

        return {
            "type": "Demo",
            "root": root,
            "destination": "demos",
        }

    # Saves
    if any(
        file.suffix.lower() == ".sav"
        for file in files
    ):

        return {
            "type": "Save",
            "root": root,
            "destination": "saves",
        }

    # Dupes
    if any(
        file.suffix.lower() == ".dupe"
        for file in files
    ):

        return {
            "type": "Dupe",
            "root": root,
            "destination": "dupes",
        }

    # Addon
    addon_folders = {
        "lua",
        "materials",
        "models",
        "sound",
        "scripts",
        "particles",
        "resource",
        "effects",
        "weapons",
        "entities",
        "gamemodes",
    }

    if top_folders & addon_folders:

        return {
            "type": "Addon",
            "root": root,
            "destination": "addons",
        }

    return {
        "type": "Unknown",
        "root": root,
        "destination": None,
    }


# ============================================================
# COPY
# ============================================================

def copy_file(source, destination):

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    shutil.copy2(
        source,
        destination
    )


def copy_contents(source, destination):

    copied = 0
    conflicts = []

    destination.mkdir(
        parents=True,
        exist_ok=True
    )

    for item in source.rglob("*"):

        if not item.is_file():
            continue

        relative = item.relative_to(source)

        target = (
            destination / relative
        )

        if target.exists():
            conflicts.append(target)

        copy_file(
            item,
            target
        )

        copied += 1

    return copied, conflicts


# ============================================================
# APPLICATION
# ============================================================

class GModInstaller(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title(
            f"{APP_NAME} {VERSION}"
        )

        self.geometry(
            "900x680"
        )

        self.minsize(
            820,
            620
        )

        self.configure(
            bg="#f4f5f7"
        )

        self.gmod_path = find_gmod()

        self.selected_file = None

        self.temp_directory = None

        self.detected = None

        self.setup_styles()

        self.create_ui()

        self.update_game_path()


    # ========================================================
    # STYLES
    # ========================================================

    def setup_styles(self):

        style = ttk.Style(self)

        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        style.configure(
            "Title.TLabel",
            font=(
                "Segoe UI",
                26,
                "bold"
            )
        )

        style.configure(
            "Subtitle.TLabel",
            font=(
                "Segoe UI",
                11
            )
        )

        style.configure(
            "Section.TLabel",
            font=(
                "Segoe UI",
                11,
                "bold"
            )
        )

        style.configure(
            "Big.TButton",
            font=(
                "Segoe UI",
                13,
                "bold"
            ),
            padding=14
        )

        style.configure(
            "Select.TButton",
            font=(
                "Segoe UI",
                11,
                "bold"
            ),
            padding=10
        )


    # ========================================================
    # UI
    # ========================================================

    def create_ui(self):

        # Main scroll-free layout designed for normal Windows
        # 100% display scaling.

        outer = ttk.Frame(
            self,
            padding=24
        )

        outer.pack(
            fill="both",
            expand=True
        )


        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        header = ttk.Frame(
            outer
        )

        header.pack(
            fill="x",
            pady=(0, 20)
        )


        ttk.Label(
            header,
            text="GMod Installer",
            style="Title.TLabel"
        ).pack(
            anchor="w"
        )


        ttk.Label(
            header,
            text=(
                "Install addons, maps, saves, dupes and more "
                "without manually finding their folders."
            ),
            style="Subtitle.TLabel"
        ).pack(
            anchor="w",
            pady=(3, 0)
        )


        # ----------------------------------------------------
        # GMOD LOCATION
        # ----------------------------------------------------

        game_box = ttk.LabelFrame(
            outer,
            text="  Garry's Mod Location  ",
            padding=12
        )

        game_box.pack(
            fill="x",
            pady=(0, 14)
        )


        self.path_var = tk.StringVar()

        path_entry = ttk.Entry(
            game_box,
            textvariable=self.path_var,
            state="readonly",
            font=(
                "Segoe UI",
                10
            )
        )

        path_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 10)
        )


        ttk.Button(
            game_box,
            text="Find GMod",
            command=self.find_game
        ).pack(
            side="right"
        )


        # ----------------------------------------------------
        # SELECT FILE
        # ----------------------------------------------------

        select_box = ttk.LabelFrame(
            outer,
            text="  Choose Something To Install  ",
            padding=14
        )

        select_box.pack(
            fill="x",
            pady=(0, 14)
        )


        self.file_var = tk.StringVar(
            value="No file selected"
        )


        file_row = ttk.Frame(
            select_box
        )

        file_row.pack(
            fill="x"
        )


        ttk.Button(
            file_row,
            text="SELECT FILE",
            style="Select.TButton",
            command=self.choose_file
        ).pack(
            side="left"
        )


        ttk.Label(
            file_row,
            textvariable=self.file_var,
            font=(
                "Segoe UI",
                10
            )
        ).pack(
            side="left",
            padx=(15, 0),
            fill="x",
            expand=True
        )


        # ----------------------------------------------------
        # DETECTION CARD
        # ----------------------------------------------------

        detection_box = ttk.LabelFrame(
            outer,
            text="  Installation Preview  ",
            padding=14
        )

        detection_box.pack(
            fill="both",
            expand=True,
            pady=(0, 14)
        )


        info = ttk.Frame(
            detection_box
        )

        info.pack(
            fill="x",
            pady=(0, 12)
        )


        # Type
        type_frame = ttk.Frame(
            info
        )

        type_frame.pack(
            side="left",
            fill="x",
            expand=True
        )


        ttk.Label(
            type_frame,
            text="DETECTED TYPE",
            font=(
                "Segoe UI",
                9,
                "bold"
            )
        ).pack(
            anchor="w"
        )


        self.type_value = tk.StringVar(
            value="—"
        )


        ttk.Label(
            type_frame,
            textvariable=self.type_value,
            font=(
                "Segoe UI",
                15,
                "bold"
            )
        ).pack(
            anchor="w",
            pady=(2, 0)
        )


        # Destination
        destination_frame = ttk.Frame(
            info
        )

        destination_frame.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(30, 0)
        )


        ttk.Label(
            destination_frame,
            text="INSTALL TO",
            font=(
                "Segoe UI",
                9,
                "bold"
            )
        ).pack(
            anchor="w"
        )


        self.destination_value = tk.StringVar(
            value="—"
        )


        ttk.Label(
            destination_frame,
            textvariable=self.destination_value,
            font=(
                "Segoe UI",
                12,
                "bold"
            )
        ).pack(
            anchor="w",
            pady=(2, 0)
        )


        # File count
        count_frame = ttk.Frame(
            info
        )

        count_frame.pack(
            side="right"
        )


        ttk.Label(
            count_frame,
            text="FILES",
            font=(
                "Segoe UI",
                9,
                "bold"
            )
        ).pack(
            anchor="e"
        )


        self.count_value = tk.StringVar(
            value="—"
        )


        ttk.Label(
            count_frame,
            textvariable=self.count_value,
            font=(
                "Segoe UI",
                15,
                "bold"
            )
        ).pack(
            anchor="e",
            pady=(2, 0)
        )


        # ----------------------------------------------------
        # DETAILS
        # ----------------------------------------------------

        self.preview = tk.Text(
            detection_box,
            height=7,
            wrap="word",
            font=(
                "Consolas",
                10
            ),
            relief="flat",
            borderwidth=0,
            background="#ffffff",
            foreground="#202124",
            padx=12,
            pady=10
        )

        self.preview.pack(
            fill="both",
            expand=True
        )

        self.preview.configure(
            state="disabled"
        )


        # ----------------------------------------------------
        # BOTTOM
        # ----------------------------------------------------

        bottom = ttk.Frame(
            outer
        )

        bottom.pack(
            fill="x"
        )


        self.status_var = tk.StringVar(
            value=""
        )


        ttk.Label(
            bottom,
            textvariable=self.status_var,
            font=(
                "Segoe UI",
                10
            )
        ).pack(
            side="left"
        )


        self.install_button = ttk.Button(
            bottom,
            text="INSTALL NOW",
            style="Big.TButton",
            command=self.install,
            state="disabled"
        )

        self.install_button.pack(
            side="right",
            ipadx=22
        )


    # ========================================================
    # PREVIEW
    # ========================================================

    def set_preview(self, text):

        self.preview.configure(
            state="normal"
        )

        self.preview.delete(
            "1.0",
            "end"
        )

        self.preview.insert(
            "1.0",
            text
        )

        self.preview.configure(
            state="disabled"
        )


    # ========================================================
    # UPDATE GAME
    # ========================================================

    def update_game_path(self):

        if self.gmod_path:

            self.path_var.set(
                str(self.gmod_path)
            )

            self.status_var.set(
                "✓ Garry's Mod detected"
            )

        else:

            self.path_var.set(
                "Garry's Mod was not found automatically"
            )

            self.status_var.set(
                "Select your garrysmod folder"
            )


    # ========================================================
    # FIND GMOD
    # ========================================================

    def find_game(self):

        found = find_gmod()

        if found:

            self.gmod_path = found

            self.update_game_path()

            messagebox.showinfo(
                "GMod Found",
                "Garry's Mod was found at:\n\n"
                + str(found)
            )

            self.update_install_button()

            return


        folder = filedialog.askdirectory(
            title="Select your garrysmod folder"
        )

        if not folder:
            return


        folder = Path(folder)


        if folder.name.lower() != "garrysmod":

            messagebox.showerror(
                "Wrong Folder",
                "Please select the actual "
                "'garrysmod' folder."
            )

            return


        self.gmod_path = folder

        self.update_game_path()

        self.update_install_button()


    # ========================================================
    # CHOOSE FILE
    # ========================================================

    def choose_file(self):

        path = filedialog.askopenfilename(

            title="Choose something to install",

            filetypes=[

                (
                    "GMod Files",
                    "*.zip *.7z *.rar *.tar *.tgz "
                    "*.gma *.bsp *.dem *.sav *.dupe"
                ),

                (
                    "All Files",
                    "*.*"
                ),

            ]

        )


        if not path:
            return


        self.clear_temp()


        self.selected_file = Path(
            path
        )


        self.file_var.set(
            self.selected_file.name
        )


        self.analyze()


    # ========================================================
    # ANALYZE
    # ========================================================

    def analyze(self):

        if not self.selected_file:
            return


        self.type_value.set(
            "Analyzing..."
        )

        self.destination_value.set(
            "Please wait..."
        )

        self.count_value.set(
            "..."
        )


        self.update()


        try:

            extension = (
                self.selected_file
                .suffix
                .lower()
            )


            # ------------------------------------------------
            # Direct files
            # ------------------------------------------------

            direct = {

                ".gma": (
                    "GMod Addon",
                    "addons"
                ),

                ".bsp": (
                    "Map",
                    "maps"
                ),

                ".dem": (
                    "Demo",
                    "demos"
                ),

                ".sav": (
                    "Save",
                    "saves"
                ),

                ".dupe": (
                    "Dupe",
                    "dupes"
                ),

            }


            if extension in direct:

                file_type, destination = direct[
                    extension
                ]


                self.detected = {

                    "type": file_type,

                    "destination": destination,

                    "root": self.selected_file.parent,

                    "direct": True,

                }


                full_destination = (

                    self.gmod_path / destination

                    if self.gmod_path

                    else Path("GMod") / destination

                )


                self.type_value.set(
                    file_type
                )

                self.destination_value.set(
                    str(full_destination)
                )

                self.count_value.set(
                    "1"
                )


                self.set_preview(

                    "This file is already in a "
                    "GMod-compatible format.\n\n"

                    "No archive extraction is needed.\n"

                    "Click INSTALL NOW to place it "
                    "in the correct folder."

                )


                self.status_var.set(
                    "✓ Ready to install"
                )


                self.update_install_button()

                return


            # ------------------------------------------------
            # Archive
            # ------------------------------------------------

            self.temp_directory = Path(
                tempfile.mkdtemp(
                    prefix="GModInstaller_"
                )
            )


            extract_archive(
                self.selected_file,
                self.temp_directory
            )


            self.detected = detect_archive(
                self.temp_directory
            )


            self.detected["direct"] = False


            root = self.detected["root"]

            file_type = self.detected["type"]

            destination_name = (
                self.detected["destination"]
            )


            files = list_files(
                root
            )


            if (
                destination_name
                and self.gmod_path
            ):

                destination = (
                    self.gmod_path
                    / destination_name
                )

            elif self.gmod_path:

                destination = (
                    self.gmod_path
                )

            else:

                destination = "GMod not selected"


            self.type_value.set(
                file_type
            )

            self.destination_value.set(
                str(destination)
            )

            self.count_value.set(
                str(len(files))
            )


            # ------------------------------------------------
            # Contents preview
            # ------------------------------------------------

            preview = (
                "Archive extracted successfully.\n\n"
                "The installer inspected the extracted "
                "files and determined the destination above.\n\n"
                "Top-level contents:\n"
            )


            try:

                for item in list(root.iterdir())[:30]:

                    if item.is_dir():

                        preview += (
                            f"  📁 {item.name}\n"
                        )

                    else:

                        preview += (
                            f"  📄 {item.name}\n"
                        )

            except Exception:
                pass


            if file_type == "Unknown":

                self.status_var.set(
                    "⚠ Could not determine installation folder"
                )

                preview += (
                    "\nThis archive could not be "
                    "confidently identified as a GMod file."
                )

            else:

                self.status_var.set(
                    "✓ Ready to install"
                )


            self.set_preview(
                preview
            )


            self.update_install_button()


        except Exception as error:

            self.detected = None

            self.type_value.set(
                "Error"
            )

            self.destination_value.set(
                "—"
            )

            self.count_value.set(
                "—"
            )

            self.status_var.set(
                "⚠ Could not analyze file"
            )


            self.set_preview(
                "Something went wrong:\n\n"
                + str(error)
            )


            self.install_button.configure(
                state="disabled"
            )


    # ========================================================
    # INSTALL BUTTON STATE
    # ========================================================

    def update_install_button(self):

        if (

            self.gmod_path

            and self.detected

            and self.detected["type"]
            != "Unknown"

        ):

            self.install_button.configure(
                state="normal"
            )

        else:

            self.install_button.configure(
                state="disabled"
            )


    # ========================================================
    # INSTALL
    # ========================================================

    def install(self):

        if not self.gmod_path:

            messagebox.showerror(
                "GMod Not Found",
                "Select your garrysmod folder first."
            )

            return


        if not self.detected:
            return


        file_type = (
            self.detected["type"]
        )


        if file_type == "Unknown":

            messagebox.showwarning(
                "Unknown File",
                "The installer couldn't determine "
                "where this belongs."
            )

            return


        destination_name = (
            self.detected["destination"]
        )


        destination = (
            self.gmod_path
            / destination_name
        )


        try:

            # =================================================
            # DIRECT FILE
            # =================================================

            if self.detected.get("direct"):

                destination.mkdir(
                    parents=True,
                    exist_ok=True
                )


                target = (
                    destination
                    / self.selected_file.name
                )


                if target.exists():

                    answer = messagebox.askyesno(
                        "File Already Exists",
                        f"{target.name} already exists.\n\n"
                        "Do you want to replace it?"
                    )

                    if not answer:
                        return


                shutil.copy2(
                    self.selected_file,
                    target
                )


                self.status_var.set(
                    "✓ Installed successfully"
                )


                messagebox.showinfo(
                    "Installed!",
                    "Installed successfully.\n\n"
                    + str(target)
                )

                return


            # =================================================
            # MAP / DEMO / SAVE / DUPE
            # =================================================

            if file_type in {
                "Map",
                "Demo",
                "Save",
                "Dupe"
            }:

                destination.mkdir(
                    parents=True,
                    exist_ok=True
                )


                extensions = {

                    "Map": {".bsp"},

                    "Demo": {".dem"},

                    "Save": {".sav"},

                    "Dupe": {".dupe"},

                }[file_type]


                files = [

                    file

                    for file in list_files(
                        self.detected["root"]
                    )

                    if file.suffix.lower()
                    in extensions

                ]


                if not files:

                    messagebox.showwarning(
                        "Nothing Found",
                        "No matching files were found."
                    )

                    return


                conflicts = [

                    destination / file.name

                    for file in files

                    if (
                        destination
                        / file.name
                    ).exists()

                ]


                if conflicts:

                    answer = messagebox.askyesno(
                        "Existing Files",
                        f"{len(conflicts)} file(s) "
                        "already exist.\n\n"
                        "Replace them?"
                    )

                    if not answer:
                        return


                for file in files:

                    copy_file(
                        file,
                        destination
                        / file.name
                    )


                self.status_var.set(
                    "✓ Installation complete"
                )


                messagebox.showinfo(
                    "Installation Complete",
                    f"Installed {len(files)} "
                    f"{file_type.lower()} file(s).\n\n"
                    f"Location:\n{destination}"
                )

                return


            # =================================================
            # ADDON
            # =================================================

            if file_type == "Addon":

                addons_folder = (
                    self.gmod_path
                    / "addons"
                )


                addons_folder.mkdir(
                    parents=True,
                    exist_ok=True
                )


                root = (
                    self.detected["root"]
                )


                contents = list(
                    root.iterdir()
                )


                if len(contents) == 1:

                    only = contents[0]

                    if only.is_dir():

                        addon_folder = (
                            addons_folder
                            / only.name
                        )

                        source = only

                    else:

                        addon_folder = (
                            addons_folder
                            / self.selected_file.stem
                        )

                        source = root

                else:

                    addon_folder = (
                        addons_folder
                        / self.selected_file.stem
                    )

                    source = root


                copied, conflicts = (
                    copy_contents(
                        source,
                        addon_folder
                    )
                )


                self.status_var.set(
                    "✓ Addon installed"
                )


                messagebox.showinfo(
                    "Addon Installed!",
                    f"Installed {copied} file(s).\n\n"
                    f"Addon location:\n"
                    f"{addon_folder}"
                )

                return


            # =================================================
            # FULL GMOD FOLDER
            # =================================================

            if file_type == "GMod Folder":

                root = (
                    self.detected["root"]
                )


                files = list_files(
                    root
                )


                for file in files:

                    relative = (
                        file.relative_to(root)
                    )


                    target = (
                        self.gmod_path
                        / relative
                    )


                    copy_file(
                        file,
                        target
                    )


                self.status_var.set(
                    "✓ Installation complete"
                )


                messagebox.showinfo(
                    "Installation Complete",
                    f"Installed {len(files)} "
                    "file(s) into Garry's Mod."
                )

        except Exception as error:

            self.status_var.set(
                "⚠ Installation failed"
            )


            messagebox.showerror(
                "Installation Failed",
                str(error)
            )


    # ========================================================
    # CLEANUP
    # ========================================================

    def clear_temp(self):

        if (
            self.temp_directory
            and self.temp_directory.exists()
        ):

            shutil.rmtree(
                self.temp_directory,
                ignore_errors=True
            )


        self.temp_directory = None


    def clear(self):

        self.clear_temp()

        self.selected_file = None

        self.detected = None

        self.file_var.set(
            "No file selected"
        )

        self.type_value.set(
            "—"
        )

        self.destination_value.set(
            "—"
        )

        self.count_value.set(
            "—"
        )

        self.status_var.set(
            ""
        )

        self.set_preview(
            ""
        )

        self.install_button.configure(
            state="disabled"
        )


    def destroy(self):

        self.clear_temp()

        super().destroy()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        app = GModInstaller()

        app.mainloop()

    except Exception as error:

        # If something unexpected happens before the GUI
        # starts, keep the error visible.
        try:

            root = tk.Tk()

            root.withdraw()

            messagebox.showerror(
                "GMod Installer Error",
                str(error)
            )

            root.destroy()

        except Exception:

            print(
                "GMod Installer Error:"
            )

            print(error)