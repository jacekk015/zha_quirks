# zha_quirks
All quirks in one place:

# Usage

1. Create a custom quirk dir in HA, e.g., /config/custom_zha_quirks
2. In configuration.yaml, point to this directory:
```
zha:
  custom_quirks_path: /config/custom_zha_quirks/
```
3. Download and put the chosen quirk file in the directory above.
4. Restart Home Assistant

# In case of errors or to support new function

1. Enable debug log level
```
logger:
  default: info
  logs:
    homeassistant.components.zha: debug
    zigpy: debug
    zhaquirks: debug
```
2. Restart Home Assistant
3. Repeat actions that create errors or enable/disable functions on the device
4. Wait for another minimum 5 minutes
5. Download Home Assistant logs - attach them as a file in new issue

# Supported TRV's and Thermostats

## trv_saswell.py
```
        MODELS_INFO: [
            ("_TZE200_yw7cahqs", "TS0601"),
            ("_TZE200_c88teujp", "TS0601"),
            ("_TZE200_azqp6ssj", "TS0601"),
            ("_TZE200_9gvruqf5", "TS0601"),
            ("_TZE200_zuhszj9s", "TS0601"),
            ("_TZE200_zr9c0day", "TS0601"),
            ("_TZE200_h4cgnbzg", "TS0601"),
            ("_TZE200_0dvm9mva", "TS0601"),
            ("_TZE200_exfrnlow", "TS0601"),
            ("_TZE200_9m4kmbfu", "TS0601"),
            ("_TZE200_3yp57tby", "TS0601"),
            ("_TZE200_mz5y07w2", "TS0601"), #Garza Smart TRV
        ],       
        MODELS_INFO: [
            ("_TYST11_KGbxAXL2", "GbxAXL2"),
            ("_TYST11_c88teujp", "88teujp"),
            ("_TYST11_azqp6ssj", "zqp6ssj"),
            ("_TYST11_yw7cahqs", "w7cahqs"),
            ("_TYST11_9gvruqf5", "gvruqf5"),
            ("_TYST11_zuhszj9s", "uhszj9s"),
            ("_TYST11_caj4jz0i", "aj4jz0i"),
        ],
```
## ts0601_temphumid.py
```
        MODELS_INFO: [
            ("_TZE200_bq5c8xfe", "TS0601"),
            ("_TZE200_locansqn", "TS0601"),
        ],     
```
## ts0601_thermostat_avatto.py
```
        MODELS_INFO: [
            ("_TZE200_ye5jkfsb", "TS0601"),
            ("_TZE200_aoclfnxz", "TS0601"),
            ("_TZE200_ztvwu4nk", "TS0601"),
            ("_TZE200_5toc8efa", "TS0601"),
            ("_TZE200_u9bfwha0", "TS0601"),
        ],    
        MODELS_INFO: [
            ("_TZE200_2ekuz3dz", "TS0601"),
            ("_TZE204_aoclfnxz", "TS0601"),
            ("_TZE204_u9bfwha0", "TS0601"),
            ("_TZE200_g9a3awaj", "TS0601"),
        ],
```
## ts0601_thermostat_avatto2.py
```
        MODELS_INFO: [
            ("_TZE204_lzriup1j", "TS0601"), #Avatto - Electric Heating version
        ],
```
## ts0601_trv_beca.py
```
        MODELS_INFO: [
            ("_TZE200_b6wax7g0", "TS0601"),
        ],
```
## ts0601_trv_etop.py
```
        MODELS_INFO: [
            ("_TZE200_0hg58wyk", "TS0601"),
        ],
```
## ts0601_trv_maxsmart.py
```
        MODELS_INFO: [
            ("_TZE200_chyvmhay", "TS0601"),
            ("_TZE200_i48qyn9s", "TS0601"), #ESSENTIALS Smart Home Heizkörperthermostat
            ("_TZE200_qc4fpmcn", "TS0601"),
            ("_TZE200_fhn3negr", "TS0601"),
            ("_TZE200_thbr5z34", "TS0601"),
            ("_TZE200_uiyqstza", "TS0601"),
        ],
```
## ts0601_trv_me167.py
```
        MODELS_INFO: [
            ("_TZE200_bvu2wnxz", "TS0601"),
            ("_TZE200_6rdj8dzm", "TS0601"),
            ("_TZE200_p3dbf6qs", "TS0601"), # model: 'ME168', vendor: 'Avatto'
            ("_TZE200_rxntag7i", "TS0601"), # model: 'ME168', vendor: 'Avatto'
            ("_TZE200_rxq4iti9", "TS0601"),
            ("_TZE200_9xfjixap", "TS0601"),
        ],
```
## ts0601_trv_moes.py
```
        MODELS_INFO: [
            ("_TZE200_ckud7u2l", "TS0601"),
            ("_TZE200_ywdxldoj", "TS0601"),
            ("_TZE200_do5qy8zo", "TS0601"),
            ("_TZE200_cwnjrr72", "TS0601"),
            ("_TZE200_pvvbommb", "TS0601"),
            ("_TZE200_9sfg7gm0", "TS0601"),
            ("_TZE200_2atgpdho", "TS0601"),
            ("_TZE200_cpmgn2cf", "TS0601"),
            ("_TZE200_8thwkzxl", "TS0601"),
            ("_TZE200_4eeyebrt", "TS0601"),
            ("_TZE200_8whxpsiw", "TS0601"),
            ("_TZE200_xby0s3ta", "TS0601"),
            ("_TZE200_7fqkphoq", "TS0601"),
            
        ],
        MODELS_INFO: [
            ("_TYST11_ckud7u2l", "kud7u2l"),
            ("_TYST11_ywdxldoj", "wdxldoj"),
            ("_TYST11_cwnjrr72", "wnjrr72"),
        ],
```
## ts0601_trv_rtitek.py
```
        MODELS_INFO: [
            ("_TZE200_a4bpgplm", "TS0601"),
            ("_TZE200_dv8abrrz", "TS0601"),
            ("_TZE200_z1tyspqw", "TS0601"),
            ("_TZE200_rtrmfadk", "TS0601"),
        ],
```
## ts0601_trv_rtitek2.py
```
        MODELS_INFO: [
            ("_TZE200_bvrlmajk", "TS0601"),
            #MOES TRV
            ("_TZE204_9mjy74mp", "TS0601"),
            ("_TZE200_9mjy74mp", "TS0601"),
            ("_TZE200_rtrmfadk", "TS0601"),
        ],
```
## ts0601_trv_siterwell.py
```
        MODELS_INFO: [
            ("_TYST11_jeaxp72v", "eaxp72v"),
            ("_TYST11_kfvq6avy", "fvq6avy"),
            ("_TYST11_zivfvd7h", "ivfvd7h"),
            ("_TYST11_hhrtiq0x", "hrtiq0x"),
            ("_TYST11_ps5v5jor", "s5v5jor"),
            ("_TYST11_owwdxjbx", "wwdxjbx"),
            ("_TYST11_8daqwrsj", "daqwrsj"),
            ("_TYST11_czk78ptr", "zk78ptr"),
        ],
        MODELS_INFO: [
            ("_TZE200_jeaxp72v", "TS0601"),
            ("_TZE200_kfvq6avy", "TS0601"),
            ("_TZE200_zivfvd7h", "TS0601"),
            ("_TZE200_hhrtiq0x", "TS0601"),
            ("_TZE200_ps5v5jor", "TS0601"),
            ("_TZE200_owwdxjbx", "TS0601"),
            ("_TZE200_8daqwrsj", "TS0601"),
            ("_TZE200_2cs6g9i7", "TS0601"), # Brennenstuhl HT CZ 01
        ],
```
## ts0601_trv_zonnsmart.py
```
        MODELS_INFO: [
            ("_TZE200_7yoranx2", "TS0601"),  # MOES TV01 ZTRV-ZX-TV01-MS
            ("_TZE200_e9ba97vf", "TS0601"),  # Zonnsmart TV01-ZG
            ("_TZE200_hue3yfsn", "TS0601"),  # Zonnsmart TV02-ZG
            ("_TZE200_husqqvux", "TS0601"),  # Tesla Smart TSL-TRV-TV01ZG
            ("_TZE200_kly8gjlz", "TS0601"),  # EARU TV05-ZG
            ("_TZE200_lnbfnyxd", "TS0601"),  # Tesla Smart TSL-TRV-TV01ZG
            ("_TZE200_mudxchsu", "TS0601"),  # Foluu TV05
            ("_TZE200_kds0pmmv", "TS0601"),  # MOES TV02
            ("_TZE200_sur6q7ko", "TS0601"),  # LSC Smart Connect 3012732
            ("_TZE200_lllliz3p", "TS0601"),  # tuya TV02-Zigbee
        ],
```
## ts0601_thermostat_zwt198.py
```
        MODELS_INFO: [
            ("_TZE200_viy9ihs7", "TS0601"),
        ],
```
