#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created: 08 settembre 2026
@author: franco buffa
"""

from pycraf import satellite, atm
import json
import requests
import numpy as np
#from matplotlib import pylab as plt
from astroquery.simbad import Simbad
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.coordinates import AltAz, get_body, solar_system_ephemeris
from datetime import datetime, UTC


def azel(source,OBSTIME,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0, WAVELENGTH = 0.013627):
  source = Simbad.query_object(source)
  RA = source["RA"][0]
  DE = source["DEC"][0]
  RADEC = SkyCoord(RA,DE, unit=(u.hourangle, u.deg))
# LOCATION = EarthLocation(lat="39d29m35.060604s", lon="9d14m42.544464s", height = 671.66650*u.m)
  LOCATION = EarthLocation.of_site('SRT')
  OBSTIME  = Time(OBSTIME)
  OBSERVER = AltAz(location= LOCATION, obstime = OBSTIME, pressure= PRESSURE * u.hPa, temperature= TEMPERATURE * u.deg_C, relative_humidity= RELATIVE_HUMIDITY, obswl= WAVELENGTH * u.meter)
  RADEC_OBSERVER = RADEC.transform_to(OBSERVER)
  return RADEC_OBSERVER.az.deg, RADEC_OBSERVER.alt.deg

def xscan(source,epoch,dt,N,ANG=2,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):

  N=int(N/2)*2+1
  M=N*2

  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el=track(source,epoch,dt,M,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)


  X0=-ANG
  x0=X0
  for i in range(N):
    # corretto per la xelev
    az[i]=x0/np.cos(np.radians(el))[k]+az[i]
    x0=X0+delta*(i+1)
  X0=ANG
  x0=X0
  for i in range(N):
    el[N+i]=x0+el[N+i]
    x0=X0-delta*(i+1)

  return t,mjd,az,el



def track(source,epoch0,dt,N,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):

  if epoch0=="NOW":
    epoch0 = Time.now()
  else:
    epoch0 = Time(epoch0)
  epoch=epoch0
  t=0
  az=[]
  el=[]
  timestamp=[]
  mjd=[]
  for i in range(N):
    az0,el0 = azel(source,epoch,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)
    az.append(az0)
    el.append(el0)
    mjd.append(epoch.to_value('mjd'))
#   da capire se la ACU accetta i secondi con i decimali
#   per clippare i decimali tagliare la stringa a 19
#   timestamp.append(str(epoch)[:19].replace('-','/'))
    timestamp.append(str(epoch)[:23].replace('-','/'))    
#   print(type(str(epoch)))
    t=t+dt
    epoch = epoch0 + t* u.second  
  return timestamp,mjd,az,el


def deg_min_sec(deg = 0.0):
    m, s = divmod(abs(deg)*3600, 60)
    d, m = divmod(m, 60)
    if deg < 0:
        d = -d
    d, m, s= int(d), int(m), int(s) 
    txt="{:03d}:{:02d}:{:02d}".format(d,m,s)
    return txt
#   return '%s:%s:%s' %(d,m,s)

def savetrack(fname,t,az,el):
   N = len(az)
   f = open(fname, 'w')
#  f.write('time, AZ, EL\n')
   for i in range(N):
     txt="{}, {}, {}".format(t[i],deg_min_sec(az[i]),deg_min_sec(el[i]))
#    print(txt)
     f.write(txt)
     f.write("\n")
#
   f.close()
   return 

def savetrack2(fname,t,az,el):
   N = len(az)
   f = open(fname, 'w')
   for i in range(N):
     txt="{}\t{}\t{}".format(t[i],az[i],el[i])
#    print(txt)
     f.write(txt)
     f.write("\n")
#
   f.close()
   return 

def download_tle():
    print('Downloading TLE data from NORAD...')
    db="norad_tle.txt"

#   tle_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
    tle_url = 'http://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=tle'

    request = requests.get(tle_url)
    f = open(db, 'w')
    f.write(request.text)
    f.close()
    print('File',db,'saved.')
    return

def tle(satname):
   print('Reading NORAD archive...')
   db="norad_tle.txt"
   f = open(db, "r")
   c=0
   for l, Line in enumerate(f):
      if c==2:       
         print(Line.strip())
         l3=Line
         break
      if c==1:       
         print(Line.strip())
         l2=Line
         c=2    
      if satname in Line:
         print('Found at line', l+1)
         print(Line.strip())
         l1=Line
         c=1
   f.close()
#  tle_string=l1+'\n'+l2+'\n'+l3        
   tle_string=l1+l2+l3        
   return tle_string

def strack(tle_string,epoch0,dt,N,REF=False):
  if epoch0=="NOW":
    epoch0 = Time.now()
  else:
    epoch0 = Time(epoch0)
  epoch=epoch0
  t=0
  az=[]
  el=[]
  timestamp=[]
  mjd=[]
  for i in range(N):
    location = EarthLocation.of_site('SRT')
    sat_obs = satellite.SatelliteObserver(location)
    az0, el0, dist = sat_obs.azel_from_sat(tle_string, epoch)  
############################################################
    if az0<0:
       az0=az0+360* u.deg
############################################################
    az.append(az0.value)
    el.append(el0.value)
    mjd.append(epoch.to_value('mjd'))
#   da capire se la ACU accetta i secondi con i decimali
#   per clippare i decimali tagliare la stringa a 19
#   timestamp.append(str(epoch)[:19].replace('-','/'))
    timestamp.append(str(epoch)[:23].replace('-','/'))
#   print(str(epoch))
#   print(type(str(epoch)))
    t=t+dt
    epoch = epoch0 + t* u.second
##########################################################
  if REF:
   print('Applying refraction correction for K band')
#  atm_layers_cache = atm.atm_layers(22 * u.GHz, atm.profile_highlat_winter)
   atm_layers_cache = atm.atm_layers(22 * u.GHz, atm.profile_midlat_summer)  
   obs_alt = 650 * u.m
   refractions = np.array([
     atm.path_endpoint(
        elev * u.deg, obs_alt, atm_layers_cache,
        ).refraction.to(u.deg).value
     for elev in el
     ])
#  il segno è cambiato per ottenere la correzione di el   
   el=el-refractions
##########################################################
  return timestamp,mjd,az,el,dist.value


def sxscan(tle_string,epoch,dt,N,ANG=2,REF=False):
  N=int(N/2)*2+1
  M=N*2
  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el,dist=strack(tle_string,epoch,dt,M,REF)
  X0=-ANG
  x0=X0
  for i in range(N):
    # corretto per la xelev
    az[i]=x0/np.cos(np.radians(el))[i]+az[i]
    x0=X0+delta*(i+1)
  X0=ANG
  x0=X0
  for i in range(N):
    el[N+i]=x0+el[N+i]
    x0=X0-delta*(i+1)
  return t,mjd,az,el

def smap(tle_string,epoch,dt,N,ANG=2,REF=False):
  N=int(N/2)*2+1
  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el,dist=strack(tle_string,epoch,dt,N*N,REF)
  segno=np.sign(el[0]-el[1])
  if segno==0:
     segno=1
  k=0
  y0=ANG*segno
  s=1
  for i in range(N):      # el loop
    x0=-ANG*s
    for j in range(N):    # az loop
      # corretto per la xelev
      az[k]=x0/np.cos(np.radians(el))[k]+az[k]
      el[k]=el[k]+y0
      x0=x0+delta*s
      k=k+1
    y0=y0-delta*segno
    s=-s
  return t,mjd,az,el

def amap(source,epoch,dt,N,ANG=2,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):
  N=int(N/2)*2+1
  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el=track(source,epoch,dt,N*N,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)
  segno=np.sign(el[0]-el[1])
  if segno==0:
     segno=1

  k=0
  y0=ANG*segno
  s=1
  for i in range(N):      # el loop
    x0=-ANG*s
    for j in range(N):    # az loop
      # corretto per la xelev
      az[k]=x0/np.cos(np.radians(el))[k]+az[k]
      el[k]=el[k]+y0
      x0=x0+delta*s
      k=k+1
    y0=y0-delta*segno
    s=-s
  return t,mjd,az,el

###########################################################################
# Funzione di formato per la stampa
def print_format(*args):
    print(*args)

    
def sched(Az,El,mapseq,proc_cmd,bck_cmd,reset_cmd,obs,prj,pth):
    vel=4.0 
    vel1=5.333333
    val0=-0.1694    
    span=0.2
    bck='TOTPOW'
    azos=0.0
    elos=0.0
    nscan=49
    di0=2 
#   sname='CUSTOM_AZ'
    sname='SAT_AZ'
    proc=mapseq
#   proc=['TSYS','OUT1','OUT2']
    az = Az + azos  
    el = El + elos  
    # Stampa le informazioni di Az, El
#    print_format('*****************************************************')
#    print_format(f'Az_corr = {az} El_corr = {el}')
#    print_format('*****************************************************')
    # Ottieni il timestamp corrente
#   now0 = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    now0 = datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
    # Controlla la variabile 'nscan'
    if nscan % 2 == 0:
        nscan += 1
    ds = np.linspace(span / 2, 0, nscan // 2 + 1)
    ds = np.concatenate((ds, -ds[-2::-1]))
    # Stampa informazioni sul passo di scansione
    print_format('*****************************************************')
    print_format('Scan step =',"{:,.6f}".format(ds[0] - ds[1]), 'deg',"({:,.6f}".format(3600 * (ds[0] - ds[1])),'arcsec)')
    print_format('*****************************************************')    
    # Genera il file LIS
    i0 = 1
    fn = f"{pth}map{now0}.lis"
    with open(fn, 'w') as fd:
#            for j in range(len(mapseq)):
#                  fd.write(f'#{sname}_{mapseq[j]}\n')
           fd.write(f'#{sname}\n')
           ff=1
           for i in range(nscan):
              if(ff==1):
                mode='INC'
              else:
                mode='DEC'
              ff=-ff
              fd.write(f'{i0}\tOTF\t{sname}\t{"{:,.4f}".format(az)}d\t{"{:,.4f}".format(el)}d\t{span}d\t0.0000d\tHOR\tHOR\tLAT\tCEN\t{mode}\t{"{:,.1f}".format(vel)}\t-HOROFFS\t0.0000d\t{"{:,.4f}".format(ds[i])}d\t-RVEL\t0.000000\tBARY\tOP\n')
              if(i0==1):
                 fd.write(f'2\tSIDEREAL\tTsys\tHOR\t{"{:,.4f}".format(az)}d\t{"{:,.4f}".format(el)}d\t-HOROFFS\t{val0}d\t{"{:,.4f}".format(ds[i])}d\t-RVEL	0.000000	BARY	OP\n')
              i0 += di0
    # Genera il file SCD
    fn = f"{pth}map{now0}.scd"
    with open(fn, 'w') as fd:
            fd.write(f'PROJECT:\t{prj}\n')
            fd.write(f'OBSERVER:\t{obs}\n')
            fd.write(f'SCANLIST:\tmap{now0}.lis\n')
            fd.write(f'BACKENDLIST:\tmap{now0}.bck\n')
            fd.write(f'PROCEDURELIST:\tmap{now0}.cfg\n')
            fd.write('MODE:\tSEQ\n')
            fd.write('SCANTAG:\t1\n')
            fd.write('INITPROC:\tPROC_INIT\n')
            fd.write('\n')

            for j in range(len(mapseq)):
                i0 = 1
                fd.write(f'SC:\t{j+1}\t{sname}_{mapseq[j]}\t{bck}:MANAGEMENT/FitsZilla\n')
                i1 = f'{j+1}_1'
                fd.write(f'{i1}\t0.000000\t2\tPROC_NULL\tPROC_{proc[j]}\n')
                for i in range(nscan):
                    i1 = f'{j+1}_{i+2}'
#                   fd.write(f'{i1}\t{"{:,.6f}".format(vel)}\t{i0}\tPROC_NULL\tPROC_NULL\n')
                    if (j+1) % 3 == 0 and i == nscan-1:
                       fd.write(f'{i1}\t{"{:,.6f}".format(vel1)}\t{i0}\tPROC_NULL\tPROC_RESET\n')
                    else:   
                       fd.write(f'{i1}\t{"{:,.6f}".format(vel1)}\t{i0}\tPROC_NULL\tPROC_NULL\n')
                    i0 += di0
                if j<len(mapseq)-1:
                    fd.write('\n')
    # Genera il file CFG
    fn = f"{pth}map{now0}.cfg"
    with open(fn, 'w') as ffd:
            ffd.write('PROC_INIT{\n')
            ffd.write('\tnop\n')
            ffd.write('}\n')
            ffd.write('PROC_NULL{\n')
            ffd.write('}\n')
            
            ffd.write('PROC_RESET{\n')
            if (reset_cmd!='NOP'):
                 ffd.write(reset_cmd)
                 ffd.write('wait=15.0\n')
            else:
                 ffd.write('\tnop\n')
            ffd.write('}\n')
            
            for j in range(len(mapseq)):                        
             ffd.write('PROC_'+proc[j]+'{\n')
#            ffd.write('clearServoOffsets\n')
             if (proc_cmd[j]!='NOP'):
                 ffd.write(proc_cmd[j])
             ffd.write('wait=15.0\n}\n')
    # Genera il file BCK
    fn = f"{pth}map{now0}.bck"
    with open(fn, 'w') as fd:
            fd.write(f'{bck}:BACKENDS/TotalPower')
            fd.write('{\n')
            if (bck_cmd!='NOP'):
                 fd.write(bck_cmd)
            fd.write('}\n')

###########################################################################
# crea le schedule OOF
def oofscd(satname,epoch,mapseq,proc_cmd,bck_cmd,reset_cmd,obs,prj,pth,DTLE):
  if (DTLE):
      download_tle()
  tle_string=tle(satname)
  t,mjd,az,el,dist=strack(tle_string,epoch,1,1)
  print('epoch',t[0])
  print('distance {:.0f} km'.format(dist)) 
  print('Az = {:.6f} deg'.format(az[0])) 
  print('El = {:.6f} deg'.format(el[0])) 
  sched(az[0],el[0],mapseq,proc_cmd,bck_cmd,reset_cmd,obs,prj,pth)
  
###########################################################################

def pmap(source,epoch,dt,N,ANG=2,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):
  N=int(N/2)*2+1
  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el=ptrack(source,epoch,dt,N*N,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)
  segno=np.sign(el[0]-el[1])
  if segno==0:
     segno=1

  k=0
  y0=ANG*segno
  s=1
  for i in range(N):      # el loop
    x0=-ANG*s
    for j in range(N):    # az loop
      # corretto per la xelev
      az[k]=x0/np.cos(np.radians(el))[k]+az[k]
      el[k]=el[k]+y0
      x0=x0+delta*s
      k=k+1
    y0=y0-delta*segno
    s=-s
  return t,mjd,az,el

def pxscan(source,epoch,dt,N,ANG=2,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):
  N=int(N/2)*2+1
  M=N*2
  delta=(2*abs(ANG))/(N-1)
  t,mjd,az,el=ptrack(source,epoch,dt,M,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)
  X0=-ANG
  x0=X0
  for i in range(N):
    # corretto per la xelev
    az[i]=x0/np.cos(np.radians(el))[i]+az[i]
    x0=X0+delta*(i+1)
  X0=ANG
  x0=X0
  for i in range(N):
    el[N+i]=x0+el[N+i]
    x0=X0-delta*(i+1)
  return t,mjd,az,el

def ptrack(source,epoch0,dt,N,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY = 0):
  if epoch0=="NOW":
    epoch0 = Time.now()
  else:
    epoch0 = Time(epoch0)
  epoch=epoch0
  t=0
  az=[]
  el=[]
  timestamp=[]
  mjd=[]
  for i in range(N):
    az0,el0 = pazel(source,epoch,PRESSURE,TEMPERATURE,RELATIVE_HUMIDITY)
    az.append(az0)
    el.append(el0)
    mjd.append(epoch.to_value('mjd'))
#   da capire se la ACU accetta i secondi con i decimali
#   per clippare i decimali tagliare la stringa a 19
#   timestamp.append(str(epoch)[:19].replace('-','/'))
    timestamp.append(str(epoch)[:23].replace('-','/'))    
#   print(type(str(epoch)))
    t=t+dt
    epoch = epoch0 + t* u.second  
  return timestamp,mjd,az,el

def pazel(source,OBSTIME,PRESSURE=0,TEMPERATURE=0,RELATIVE_HUMIDITY=0,WAVELENGTH=0.013627):
   with solar_system_ephemeris.set('builtin'):
        OBSTIME  = Time(OBSTIME)
   LOCATION = EarthLocation.of_site('SRT')
   source = get_body(source, OBSTIME, LOCATION)
   sistema_riferimento_altaz = AltAz(obstime=OBSTIME, location=LOCATION, pressure= PRESSURE * u.hPa,
          temperature= TEMPERATURE * u.deg_C, relative_humidity= RELATIVE_HUMIDITY, obswl= WAVELENGTH * u.meter)
   altaz = source.transform_to(sistema_riferimento_altaz)
   return altaz.az.deg, altaz.alt.deg   


