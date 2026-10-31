"""Offline, read-only TalkNet scoring. Never downloads assets or changes audio.

Requires FOCUS_TALKNET_SOURCE, FOCUS_TALKNET_WEIGHTS and a local face cascade.
Input/output JSON files contain local media paths and temporal scores, not tokens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys


def main():
    import cv2
    import numpy as np
    import python_speech_features
    import soundfile as sf
    import torch

    request = json.loads(Path(sys.argv[1]).read_text())
    source = Path(os.environ['FOCUS_TALKNET_SOURCE'])
    weights = Path(os.environ['FOCUS_TALKNET_WEIGHTS'])
    if not weights.is_file():
        raise RuntimeError('TalkNet weights are missing; automatic downloads are disabled')
    if not torch.cuda.is_available():
        raise RuntimeError('TalkNet CUDA runtime is unavailable')
    def offline(*args, **kwargs):
        raise RuntimeError('Network access is disabled during TalkNet inference')
    socket.socket.connect = offline
    sys.path.insert(0, str(source))
    from model.talkNetModel import talkNetModel
    from loss import lossAV

    torch.set_num_threads(2)
    model, head = talkNetModel().cuda().eval(), lossAV().cuda().eval()
    state = torch.load(str(weights), map_location='cpu', weights_only=True)
    state = {k.removeprefix('module.'): v for k, v in state.items()}
    model.load_state_dict({k[6:]: v for k, v in state.items() if k.startswith('model.')}, strict=True)
    head.load_state_dict({k[7:]: v for k, v in state.items() if k.startswith('lossAV.')}, strict=True)
    audio, rate = sf.read(request['audio'], dtype='float32')
    if rate != 16000 or audio.ndim != 1:
        raise ValueError('TalkNet requires canonical mono 16k audio')
    # Upstream preprocessing uses PCM16 magnitude for MFCCs.
    features = python_speech_features.mfcc(np.clip(audio * 32768, -32768, 32767),
                                          rate, numcep=13, winlen=.025, winstep=.010)
    cascade = cv2.CascadeClassifier(os.environ.get('FOCUS_FACE_CASCADE') or
                                    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if cascade.empty():
        raise RuntimeError('Local face cascade is unavailable')
    cap = cv2.VideoCapture(request['video'])
    from_bbox = tuple(request['bbox'])
    def overlap(a, b):
        x,y,w,h=a; u,v,p,q=b
        inter=max(0,min(x+w,u+p)-max(x,u))*max(0,min(y+h,v+q)-max(y,v))
        return inter / max(1, w*h+p*q-inter)
    def upper(frame, box):
        x,y,w,h=map(int,box)
        crop=frame[y:y+max(1,h//2),x:x+w]
        return cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(32,16)).astype(float)/255
    def face_crop(frame, box):
        x,y,w,h=map(float,box); bs=max(w,h)/2; mx=x+w/2;my=y+h/2;pad=int(bs*1.8)+1
        image=np.pad(frame,((pad,pad),(pad,pad),(0,0)),constant_values=110)
        crop=image[int(my+pad-bs):int(my+pad+bs*1.8),int(mx+pad-bs*1.4):int(mx+pad+bs*1.4)]
        return cv2.cvtColor(cv2.resize(crop,(224,224)),cv2.COLOR_BGR2GRAY)[56:168,56:168]
    windows=[]
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC,request.get('timestamp_ms',0))
        ok, anchor=cap.read()
        if not ok:
            raise RuntimeError('The selected face anchor cannot be decoded')
        if tuple((anchor.shape[1],anchor.shape[0])) != tuple(request['frame_size']):
            raise ValueError('Selected face geometry does not match video')
        template=upper(anchor,from_bbox)
        cap.set(cv2.CAP_PROP_POS_MSEC,0)
        current_ms=-1.;current_frame=None
        def read_at(timestamp_ms):
            nonlocal current_ms,current_frame
            while current_ms+.001 < timestamp_ms:
                ok,frame=cap.read()
                if not ok:return None
                current_frame=frame
                current_ms=cap.get(cv2.CAP_PROP_POS_MSEC)
            return current_frame
        duration=min(len(audio)/16000,180)
        # Bound memory and inference latency. Only reliably tracked frames are scored.
        for start in range(0,int(duration),4):
            end=min(duration,start+4); n=int((end-start)*25)
            if n < 25:
                continue
            frames=[]; valid=[]; box=from_bbox; tracked=False
            for i in range(n):
                ts=start+i/25
                frame=read_at(ts*1000)
                if frame is None: break
                if i%5==0:
                    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                    scale=min(1,640/frame.shape[1]); small=cv2.resize(gray,None,fx=scale,fy=scale)
                    boxes=[tuple(int(v/scale) for v in b) for b in
                           cascade.detectMultiScale(small,1.1,5,minSize=(24,24))]
                    matches=[b for b in boxes if overlap(b,box)>=.35 and overlap(b,from_bbox)>=.2]
                    tracked=False
                    if matches:
                        candidate=max(matches,key=lambda b:overlap(b,box))
                        # Appearance check rejects many cuts; not face recognition.
                        if np.mean(np.abs(upper(frame,candidate)-template))<.22:
                            box=candidate;tracked=True
                frames.append(face_crop(frame,box));valid.append(tracked)
            n=min(len(frames),len(features)//4-start*25)
            if n<25 or sum(valid[:n])/n<.8:
                continue
            a=torch.tensor(features[start*100:start*100+n*4],dtype=torch.float32,device='cuda')[None]
            v=torch.tensor(np.array(frames[:n]),dtype=torch.float32,device='cuda')[None]
            with torch.inference_mode():
                ae=model.forward_audio_frontend(a);ve=model.forward_visual_frontend(v)
                ae,ve=model.forward_cross_attention(ae,ve)
                scores=head(model.forward_audio_visual_backend(ae,ve)).tolist()
            for i,score in enumerate(scores):
                if valid[i] and np.isfinite(score):
                    windows.append({'start_ms':round((start+i/25)*1000),
                                    'end_ms':round((start+(i+1)/25)*1000),'score':float(score)})
    finally:
        cap.release()
    Path(sys.argv[2]).write_text(json.dumps({'kind':'av_sync_v1','model':'TalkNet-TalkSet',
        'provisional':True,'windows':windows,'notice':'Experimental face/audio association; confirm by listening.'}))


if __name__ == '__main__':
    main()
