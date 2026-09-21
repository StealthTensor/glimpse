CC ?= gcc
CFLAGS ?= -fPIC -fno-stack-protector -Wall -Wextra -O2
LDFLAGS ?= -shared
LIBPAM ?= -lpam

TARGET = pam_glimpse.so
SRC = pam_glimpse.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LIBPAM)

clean:
	rm -f $(TARGET)

install: $(TARGET)
	install -m 0755 -d /lib/security
	install -m 0644 $(TARGET) /lib/security/

.PHONY: all clean install
