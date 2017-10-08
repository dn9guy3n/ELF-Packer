from enum import Enum
import sys
import logging
from pwn import *
from struct import *

EI_NIDENT = 16
ELF32_EHDR_SZ = 36 + EI_NIDENT

ETYPE_DIC = {
    0: 'No file type',
    1: 'Relocatable file',
    2: 'Executable file',
    3: 'Shared object file',
    4: 'Core file'
}


# Enum of the section types
class SectionType(Enum):
    SHT_NULL = 0
    SHT_PROGBITS = 1
    SHT_SYMTAB = 2
    SHT_STRTAB = 3
    SHT_RELA = 4
    SHT_HASH = 5
    SHT_DYNAMIC = 6
    SHT_NOTE = 7
    SHT_NOBITS = 8
    SHT_REL = 9
    SHT_SHLIB = 10
    SHT_DYNSYM = 11
    SHT_LOPROC = 0x70000000
    SHT_HIPROC = 0x7fffffff
    SHT_LOUSER = 0x80000000
    SHT_HIUSER = 0xffffffff

class Section():
    def __init__(self, sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
                 sh_link, sh_info, sh_addralign, sh_entsize):
        self.sh_name = sh_name
        self.sh_type = sh_type
        self.sh_flags = sh_flags
        self.sh_addr = sh_addr
        self.sh_offset = sh_offset
        self.sh_size = sh_size
        self.sh_link = sh_link
        self.sh_info = sh_info
        self.sh_addralign = sh_addralign
        self.sh_entsize = sh_entsize
    def __str__(self):
        return f"""[Start Section '{self.name}']
        sh_name      = {hex(self.sh_name)}
        sh_type      = {hex(self.sh_type)}
        sh_flags     = {hex(self.sh_flags)}
        sh_addr      = {hex(self.sh_addr)}
        sh_offset    = {hex(self.sh_offset)}
        sh_size      = {hex(self.sh_size)}
        sh_link      = {hex(self.sh_link)}
        sh_info      = {hex(self.sh_info)}
        sh_addralign = {hex(self.sh_addralign)}
        sh_entsize   = {hex(self.sh_entsize)}
        """

class Elf():
    def __init__(self, name="", data=[]):
        self.name = name
        self.data = data

    """
    Parse the ELF header of the binary

    e_ident:        marks the file as an object file
    e_type:         identifies the object file type
    e_machine:      specifies the required architecture of the file
    e_version:      identifies the object file version
    e_entry:        virtual address where the system first transfers control
    e_phoff:        program header table file offset in bytes
    e_shoff:        section header table offset in bytes
    e_flags:        holds processor specific flags associated with the file
    e_ehsize:       the elf header size in bytes
    e_phentsize:    size in bytes of one entry in program header table
    e_phnum:        number of entries in program header table
    e_shentsize:    size in bytes of one section header in section header table
    e_shnum:        number of entries in section header table
    e_shstrndx:     index of the section header table for string table
    """

    def parse_header(self):
        (self.e_ident, self.e_type, self.e_machine, self.e_version,
         self.e_entry, self.e_phoff, self.e_shoff, self.e_flags, self.e_ehsize,
         self.e_phentsize, self.e_phnum,
         self.e_shentsize, self.e_shnum, self.e_shstrndx) = unpack(
             f"{EI_NIDENT}sHHIIIIIHHHHHH", self.data[:ELF32_EHDR_SZ])
        logging.debug(f"entry point found:\t{hex(self.e_entry)}")
        logging.debug(f"object file type:\t{ETYPE_DIC[self.e_type]}")

    """
    Parse sections of the Section Header Table

    sh_name:        index into the string table of the section name
    sh_type:        categorizes the sections contents and semantics
    sh_flags:       flags that describe miscellaneous attributes
    sh_addr:        virtual address of the first byte when in memory (if)
    sh_offset:      offset from start of file of first byte in the section
    sh_size:        the size of the section in bytes
    sh_link:        section header table index link
    sh_info:        holds extra information depending on section type
    sh_addralign:   dictates if the section has some form of size alignment
    sh_entsize:     size in bytes of each entry of section-fixed size table
    """

    def parse_sections_header(self):
        # dictionary of arrays indexed by section type
        self.sections = {}
        section_header_sz = self.e_shnum * self.e_shentsize
        section_table = self.data[self.e_shoff:
                                  self.e_shoff + section_header_sz]
        # skip the first section in the section header table
        # e_shstrndx:     index of the section header table for string table
        for sec_index in range(1, self.e_shnum):
            # unpack the section data
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link,
             sh_info, sh_addralign, sh_entsize) = unpack(
                 'IIIIIIIIII',
                 section_table[sec_index * self.e_shentsize:sec_index * self.
                               e_shentsize + self.e_shentsize])
            # create the section
            sec = Section(sh_name, sh_type, sh_flags, sh_addr, sh_offset,
                          sh_size, sh_link, sh_info, sh_addralign, sh_entsize)
            if (not self.sections.get(sh_type)):
                self.sections[sh_type] = []
            self.sections[sh_type].append(sec)
            if sec_index == self.e_shstrndx:
                self.string_table_offset = sh_offset
        
        # add the section name to each section object
        for sec_type in self.sections.keys():
            for sec in self.sections.get(sec_type):
                sec.name = self.get_string(sec.sh_name)   
                logging.debug(sec)
    
    def find_cave(self, required_size):
        # ensure that we don't look at 'SHT_NOBITS' sections
        for sec_type in self.sections.keys():
            for sec in self.sections.get(sec_type):
                if sec.sh_type == SectionType.SHT_NOBITS:
                    continue
                index = 0
                seen_nulls = 0
                checkpoint = 0
                while (index < sec.sh_size):
                    char = self.data[sec.sh_offset + index]
                    index+=1
                    if char == 0:
                        seen_nulls += 1
                    else:
                        checkpoint = index
                        seen_nulls = 0
                    if seen_nulls == required_size:
                        break
                if seen_nulls < required_size:
                    continue
                logging.debug(f"""found a code cave in section: {sec.name} with
                        required size of {required_size} bytes at address
                        {hex(sec.sh_offset + checkpoint)} in the file. The address in memory
                        would be {hex(sec.sh_addr + index)}""")
                return (sec.sh_addr + checkpoint, sec.sh_offset + checkpoint)
        logging.error("no code cave found")

    def get_string(self, index):
        elf_str = ''
        char = self.data[self.string_table_offset + index]
        while (char != 0):
            index += 1
            elf_str += chr(char)
            char = self.data[self.string_table_offset + index]
        return elf_str

    def get_section(self, name):
        for sec_type in self.sections.keys():
            for sec in self.sections.get(sec_type):
                if sec.name == name:
                    return sec


    def pack_code(self, key):
        text_sec = self.get_section('.text')
        for i in range(text_sec.sh_size):
            self.data[text_sec.sh_offset + i] ^= key

    def change_ep(self, new_ep):
        self.data[24:24+4] = p32(new_ep)
    
    def create_unpacker(self):
        text_sec = self.get_section('.text')
        text_addr = text_sec.sh_addr & 0xFFFFF000
        unpacker_asm = asm(f"""
        push eax
        push edi
        push esi
        push edx
        push ecx

        mov eax, 0x7d
        mov ebx, {text_addr}
        mov ecx, {text_sec.sh_size}
        mov edx, 0x7 
        int 0x80 

        mov edi, {text_sec.sh_addr}
        mov esi, edi
        mov ecx, {text_sec.sh_size}
        cld
        decrypt:
            lodsb
            xor al, 0xa5
            stosb
            loop decrypt

        mov eax, 0x7d
        mov ebx, {text_addr}
        mov ecx, {text_sec.sh_size}
        mov edx, 0x5
        int 0x80

        pop ecx
        pop edx
        pop esi
        pop edi
        pop eax
 
        push {self.e_entry}
        ret
        """)
        return unpacker_asm

    def write_unpacker(self, asm, off):
        self.data[unpacker_off:unpacker_off+len(asm)] = asm

# binary.write_unpacker(unpacker_asm, unpacker_off) 
if __name__ == '__main__':

    context.arch = 'i386'

    logging.basicConfig(
        format='%(levelname)s:\t%(message)s', level=logging.DEBUG)

    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file.elf>")
        sys.exit(1)

    # load data into memory
    try:
        with open(sys.argv[1], 'rb') as f:
            elf_data = bytearray(f.read())
    except:
        print(f"ERROR: Failed opening file: {sys.argv[1]}")
        sys.exit(1)

    # check header
    if elf_data[:4] != b'\x7fELF':
        print(f"ERROR: File: {sys.argv[1]} is not an ELF file")
        sys.exit(1)

    binary = Elf(name=sys.argv[1], data=elf_data)
    binary.parse_header()
    binary.parse_sections_header()
    binary.pack_code(0xa5)
    unpacker_asm = binary.create_unpacker()
    logging.debug(f"need {len(unpacker_asm)} bytes in a cave")
    (unpacker_addr, unpacker_off) = binary.find_cave(len(unpacker_asm))
    binary.change_ep(unpacker_addr)
    binary.write_unpacker(unpacker_asm, unpacker_off) 

    # save packed binary to new file
    with open(f"{sys.argv[1]}.packed", 'wb') as f:
        f.write(binary.data)
        
