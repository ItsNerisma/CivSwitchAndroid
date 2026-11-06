pkg install -y tsu
su -c "setenforce 0"
su -c "cp ./sudo /data/data/com.termux/files/usr/bin/sudo"
su -c "chmod +x /data/data/com.termux/files/usr/bin/sudo"
su -c "setenforce 1"
echo done
