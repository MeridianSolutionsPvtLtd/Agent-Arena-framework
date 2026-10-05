import React, { useEffect } from 'react';

export default function AnimationPopup({ onComplete }) {
  useEffect(() => {
    const cv = document.getElementById('cv');
    if(!cv) return;
    const ctx = cv.getContext('2d');
    function setSize(){ cv.width=cv.offsetWidth; cv.height=cv.offsetHeight; }
    setSize();
    window.addEventListener('resize', setSize);
    
    const W=()=>cv.width, H=()=>cv.height;

    const BLUE='#1a56ff', GREEN='#10b981', LBLUE='#3b82f6', LGREEN='#34d399';
    const PHASES=[
      {at:0,  tag:'compiling',        main:'Compiling your agent',        sub:'Drawing system architecture...'},
      {at:20, tag:'wiring',           main:'Wiring the pipeline',         sub:'Connecting nodes & data flows...'},
      {at:42, tag:'injecting logic',  main:'Injecting business logic',    sub:'Rules · conditions · triggers...'},
      {at:62, tag:'electrifying',     main:'Electrifying the system',     sub:'Powering up all subsystems...'},
      {at:82, tag:'final sync',       main:'Final synchronization',       sub:'Handshaking with Meridian cloud...'},
      {at:95, tag:'deploying',        main:'Deploying agent',             sub:'Going live...'},
    ];

    let progress=0, t=0, ended=false, endT=0, lastPhase=-1, raf;

    const NODE_DEFS=[
      {id:'input',    x:.18, y:.22, w:100, h:52, label:'INPUT',      sub:'Data stream',   col:BLUE,   appear:5},
      {id:'nlp',      x:.18, y:.52, w:100, h:52, label:'NLP ENGINE', sub:'Language',      col:BLUE,   appear:12},
      {id:'memory',   x:.18, y:.72, w:100, h:52, label:'MEMORY',     sub:'Vector store',  col:LBLUE,  appear:18},
      {id:'logic',    x:.43, y:.35, w:110, h:52, label:'LOGIC CORE', sub:'Rule engine',   col:BLUE,   appear:25},
      {id:'api',      x:.43, y:.62, w:110, h:52, label:'API LAYER',  sub:'Connectors',    col:GREEN,  appear:32},
      {id:'scheduler',x:.68, y:.22, w:118, h:52, label:'SCHEDULER',  sub:'Task queue',    col:LBLUE,  appear:38},
      {id:'output',   x:.68, y:.52, w:118, h:52, label:'OUTPUT',     sub:'Response gen',  col:GREEN,  appear:45},
      {id:'monitor',  x:.68, y:.72, w:118, h:52, label:'MONITOR',    sub:'Health checks', col:BLUE,   appear:52},
    ];

    const EDGE_DEFS=[
      {from:'input',   to:'logic',     appear:28},
      {from:'nlp',     to:'logic',     appear:30},
      {from:'memory',  to:'api',       appear:34},
      {from:'logic',   to:'scheduler', appear:40},
      {from:'logic',   to:'output',    appear:42},
      {from:'api',     to:'output',    appear:44},
      {from:'api',     to:'monitor',   appear:46},
      {from:'output',  to:'monitor',   appear:54},
      {from:'scheduler',to:'output',   appear:56},
    ];

    const edgeParticles=[];
    function spawnEdgeParticle(edge){
      edgeParticles.push({edge, t:0, speed:0.006+Math.random()*0.006, life:1});
    }

    const burstP=[], shockwaves=[];
    function spawnBurst(){
      const cx=W()/2, cy=H()/2;
      const cols=[BLUE,GREEN,LBLUE,LGREEN,'#fff','#bfdbfe'];
      for(let i=0;i<130;i++){
        const a=Math.random()*Math.PI*2, sp=Math.random()*7+1;
        burstP.push({x:cx,y:cy,vx:Math.cos(a)*sp,vy:Math.sin(a)*sp,
          life:1,decay:0.007+Math.random()*0.01,r:Math.random()*3.5+0.5,
          col:cols[Math.floor(Math.random()*cols.length)],
          isStar:Math.random()<0.2,rot:Math.random()*Math.PI*2,rotV:(Math.random()-.5)*0.2});
      }
      shockwaves.push({r:10,life:1,col:BLUE},{r:10,life:0.65,col:GREEN},{r:10,life:0.35,col:LBLUE});
    }

    function getNode(id){ return NODE_DEFS.find(n=>n.id===id); }
    function nodeRect(n){
      const w=W(),h=H();
      const nw=n.w, nh=n.h;
      return { x:n.x*w - nw/2, y:n.y*h - nh/2, w:nw, h:nh, cx:n.x*w, cy:n.y*h };
    }

    function updateUI(pct){
      let idx=0;
      for(let i=PHASES.length-1;i>=0;i--){ if(pct>=PHASES[i].at){idx=i;break;} }
      if(idx!==lastPhase){
        lastPhase=idx;
        const p=PHASES[idx];
        const pTxt = document.getElementById('phase-txt');
        const mTxt = document.getElementById('main-txt');
        const sTxt = document.getElementById('sub-txt');
        if(pTxt) pTxt.textContent=p.tag;
        if(mTxt) mTxt.textContent=p.main;
        if(sTxt) sTxt.textContent=p.sub;
        ['phase-row','main-txt','sub-txt'].forEach(id=>{
          const el=document.getElementById(id);
          if(el){ el.classList.remove('in'); void el.offsetWidth; el.classList.add('in'); }
        });
      }
      const bFill = document.getElementById('bar-fill');
      const bPct = document.getElementById('bar-pct');
      if(bFill) bFill.style.width=pct+'%';
      if(bPct) bPct.textContent=Math.round(pct)+'%';
    }

    function drawNode(n, prog){
      if(prog<=0) return;
      const ap=Math.min(1,prog);
      const r=nodeRect(n);
      const isLive=progress>=62; 

      ctx.save();
      ctx.globalAlpha=ap;

      if(!isLive || progress<62+12){
        const blendToLive=isLive ? Math.min(1,(progress-62)/12)*ap : 0;

        ctx.beginPath(); ctx.roundRect(r.x,r.y,r.w,r.h,6);
        ctx.strokeStyle=n.col+'99';
        ctx.setLineDash([4,3]);
        ctx.lineWidth=1;
        ctx.stroke();
        ctx.setLineDash([]);

        const tick=8;
        [[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]].forEach(([cx2,cy2],i)=>{
          const dx=i%2===0?1:-1, dy=i<2?1:-1;
          ctx.beginPath();
          ctx.moveTo(cx2+dx*tick,cy2); ctx.lineTo(cx2,cy2); ctx.lineTo(cx2,cy2+dy*tick);
          ctx.strokeStyle=n.col; ctx.lineWidth=1.5; ctx.setLineDash([]); ctx.stroke();
        });

        if(blendToLive>0){
          ctx.beginPath(); ctx.roundRect(r.x,r.y,r.w,r.h,6);
          ctx.fillStyle=n.col+Math.floor(blendToLive*20).toString(16).padStart(2,'0');
          ctx.fill();
        }

        ctx.font=`600 9px 'Courier New',monospace`;
        ctx.fillStyle=n.col;
        ctx.textAlign='center';
        ctx.fillText(n.label, r.cx, r.cy-4);
        ctx.font=`400 9px 'Courier New',monospace`;
        ctx.fillStyle='#64748b';
        ctx.fillText(n.sub, r.cx, r.cy+9);

      } else {
        const liveP=Math.min(1,(progress-62-12)/10);

        ctx.beginPath(); ctx.roundRect(r.x,r.y,r.w,r.h,8);
        ctx.fillStyle='#fff';
        ctx.shadowColor=n.col; ctx.shadowBlur=12*liveP;
        ctx.fill(); ctx.shadowBlur=0;
        ctx.strokeStyle=n.col+Math.floor((0.4+0.4*liveP)*255).toString(16).padStart(2,'0');
        ctx.lineWidth=1.5; ctx.stroke();

        const dp=0.5+0.5*Math.sin(t*0.09+n.x*10);
        ctx.beginPath(); ctx.arc(r.x+12,r.cy-4,3.5,0,Math.PI*2);
        ctx.fillStyle=n.col; ctx.fill();
        ctx.beginPath(); ctx.arc(r.x+12,r.cy-4,7*dp,0,Math.PI*2);
        ctx.fillStyle=n.col+'33'; ctx.fill();

        ctx.font=`600 10px Segoe UI`;
        ctx.fillStyle='#1e293b'; ctx.textAlign='left';
        ctx.fillText(n.label, r.x+22, r.cy);
        ctx.font=`400 9px Segoe UI`;
        ctx.fillStyle='#94a3b8';
        ctx.fillText(n.sub, r.x+22, r.cy+12);

        ctx.beginPath(); ctx.roundRect(r.x+r.w-38,r.y+6,32,14,7);
        ctx.fillStyle='#ecfdf5'; ctx.fill();
        ctx.font=`500 8px Segoe UI`; ctx.fillStyle='#10b981'; ctx.textAlign='center';
        ctx.fillText('LIVE',r.x+r.w-22,r.y+16);
      }

      ctx.restore();
    }

    function drawEdge(e, prog){
      if(prog<=0) return;
      const ap=Math.min(1,prog);
      const na=getNode(e.from), nb=getNode(e.to);
      const ra=nodeRect(na), rb=nodeRect(nb);

      const x1=ra.x+ra.w, y1=ra.cy;
      const x2=rb.x, y2=rb.cy;
      const mx=(x1+x2)/2;

      const totalLen=Math.abs(mx-x1)+Math.abs(y2-y1)+Math.abs(x2-mx);
      const drawLen=totalLen*ap;

      ctx.save();
      ctx.strokeStyle=(progress>=62) ? e.fromCol||BLUE : (e.fromCol||BLUE)+'66';
      ctx.lineWidth=(progress>=62)?1.5:0.8;
      ctx.setLineDash(progress>=62?[]:[3,4]);
      ctx.beginPath();

      let drawn=0;
      const seg1=Math.abs(mx-x1);
      const seg2=Math.abs(y2-y1);
      const seg3=Math.abs(x2-mx);

      ctx.moveTo(x1,y1);
      if(drawn+seg1<=drawLen){
        ctx.lineTo(mx,y1); drawn+=seg1;
        if(drawn+seg2<=drawLen){
          ctx.lineTo(mx,y2); drawn+=seg2;
          if(drawn+seg3<=drawLen){
            ctx.lineTo(x2,y2);
          } else {
            const frac=(drawLen-drawn)/seg3;
            ctx.lineTo(mx+frac*(x2-mx),y2);
          }
        } else {
          const frac=(drawLen-drawn)/seg2;
          ctx.lineTo(mx,y1+frac*(y2-y1));
        }
      } else {
        const frac=drawLen/seg1;
        ctx.lineTo(x1+frac*(mx-x1),y1);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      if(ap>0.95 && progress>=42){
        const headX=rb.x, headY=rb.cy;
        ctx.beginPath();
        ctx.moveTo(headX,headY);
        ctx.lineTo(headX-7,headY-4);
        ctx.lineTo(headX-7,headY+4);
        ctx.closePath();
        ctx.fillStyle=(progress>=62)?BLUE:BLUE+'66';
        ctx.fill();
      }
      ctx.restore();
    }

    let scanX=0;
    function drawScanLine(){
      if(progress>78) return;
      scanX = (progress/78)*W();
      ctx.save();
      const grad=ctx.createLinearGradient(scanX-40,0,scanX+2,0);
      grad.addColorStop(0,'rgba(26,86,255,0)');
      grad.addColorStop(1,'rgba(26,86,255,0.12)');
      ctx.fillStyle=grad;
      ctx.fillRect(0,0,scanX,H());

      ctx.beginPath(); ctx.moveTo(scanX,0); ctx.lineTo(scanX,H());
      ctx.strokeStyle='rgba(26,86,255,0.4)'; ctx.lineWidth=1.5; ctx.stroke();
      ctx.restore();
    }

    function drawGrid(){
      const step=32;
      ctx.save();
      ctx.strokeStyle='rgba(26,86,255,0.045)';
      ctx.lineWidth=0.5;
      for(let x=0;x<W();x+=step){ ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H());ctx.stroke(); }
      for(let y=0;y<H();y+=step){ ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W(),y);ctx.stroke(); }
      ctx.fillStyle='rgba(26,86,255,0.08)';
      for(let x=0;x<W();x+=step)
        for(let y=0;y<H();y+=step){
          ctx.beginPath(); ctx.arc(x,y,1,0,Math.PI*2); ctx.fill();
        }
      ctx.restore();
    }

    function drawElectricArcs(){
      if(progress<62) return;
      const p=Math.min(1,(progress-62)/20);
      const arcs=Math.floor(p*5);
      ctx.save();
      for(let i=0;i<arcs;i++){
        const na=NODE_DEFS[Math.floor(Math.random()*NODE_DEFS.length)];
        const nb=NODE_DEFS[Math.floor(Math.random()*NODE_DEFS.length)];
        if(na===nb) continue;
        const ra=nodeRect(na), rb=nodeRect(nb);
        ctx.beginPath();
        ctx.moveTo(ra.cx,ra.cy);
        const steps=5;
        for(let j=1;j<steps;j++){
          const frac=j/steps;
          const bx=ra.cx+(rb.cx-ra.cx)*frac + (Math.random()-.5)*30;
          const by=ra.cy+(rb.cy-ra.cy)*frac + (Math.random()-.5)*30;
          ctx.lineTo(bx,by);
        }
        ctx.lineTo(rb.cx,rb.cy);
        ctx.strokeStyle=`rgba(26,86,255,${0.06+Math.random()*0.08})`;
        ctx.lineWidth=0.8; ctx.stroke();
      }
      ctx.restore();
    }

    function draw(){
      if(cv.width !== cv.offsetWidth || cv.height !== cv.offsetHeight) setSize();
      const w=W(), h=H();
      ctx.clearRect(0,0,w,h);
      ctx.fillStyle='#fff'; ctx.fillRect(0,0,w,h);
      t++;

      drawGrid();

      if(!ended){
        const sm=progress<90?1:1+(progress-90)/5;
        progress=Math.min(100,progress+0.155*sm);
        updateUI(progress);

        drawScanLine();

        if(progress>=62){
          const ep=Math.min(1,(progress-62)/20);
          ctx.fillStyle=`rgba(239,246,255,${ep*0.4})`; ctx.fillRect(0,0,w,h);
        }

        drawElectricArcs();

        EDGE_DEFS.forEach(e=>{
          const ap=Math.max(0,Math.min(1,(progress-e.appear)/10));
          e.fromCol = getNode(e.from)?.col || BLUE;
          drawEdge(e,ap);
        });

        if(progress>=62){
          if(t%12===0){
            const e=EDGE_DEFS[Math.floor(Math.random()*EDGE_DEFS.length)];
            if(progress>=e.appear) spawnEdgeParticle(e);
          }
          edgeParticles.forEach(p=>{
            p.t=Math.min(1,p.t+p.speed);
            const e=p.edge;
            const na=getNode(e.from), nb=getNode(e.to);
            const ra=nodeRect(na), rb=nodeRect(nb);
            const x1=ra.x+ra.w, y1=ra.cy, x2=rb.x, y2=rb.cy;
            const mx=(x1+x2)/2;
            const seg1=Math.abs(mx-x1), seg2=Math.abs(y2-y1), seg3=Math.abs(x2-mx);
            const total=seg1+seg2+seg3;
            const dist=p.t*total;
            let px2,py2;
            if(dist<seg1){px2=x1+(dist/seg1)*(mx-x1);py2=y1;}
            else if(dist<seg1+seg2){px2=mx;py2=y1+((dist-seg1)/seg2)*(y2-y1);}
            else{px2=mx+((dist-seg1-seg2)/seg3)*(x2-mx);py2=y2;}
            ctx.beginPath(); ctx.arc(px2,py2,3.5,0,Math.PI*2);
            ctx.fillStyle=BLUE+'cc'; ctx.fill();
            ctx.beginPath(); ctx.arc(px2,py2,7,0,Math.PI*2);
            ctx.fillStyle=BLUE+'22'; ctx.fill();
          });
          edgeParticles.splice(0,edgeParticles.length,...edgeParticles.filter(p=>p.t<1));
        }

        NODE_DEFS.forEach(n=>{
          const ap=Math.max(0,(progress-n.appear)/10);
          drawNode(n,ap);
        });

        if(progress>97){
          const fa=(progress-97)/3*0.5;
          ctx.fillStyle=`rgba(255,255,255,${fa})`; ctx.fillRect(0,0,w,h);
        }
        if(progress>=100){
          ended=true; endT=0;
          spawnBurst();
          const bw = document.getElementById('bar-wrap');
          if(bw) bw.style.opacity='0';
        }

      } else {
        endT++;

        ctx.fillStyle='rgba(239,246,255,0.4)'; ctx.fillRect(0,0,w,h);

        shockwaves.forEach(sw=>{
          sw.r+=5.5; sw.life-=0.022;
          if(sw.life>0){
            ctx.beginPath(); ctx.arc(w/2,h/2,sw.r,0,Math.PI*2);
            ctx.strokeStyle=sw.col+Math.floor(sw.life*100).toString(16).padStart(2,'0');
            ctx.lineWidth=1.5; ctx.stroke();
          }
        });
        shockwaves.splice(0,shockwaves.length,...shockwaves.filter(s=>s.life>0));

        burstP.forEach(p=>{
          p.x+=p.vx; p.y+=p.vy; p.vx*=0.96; p.vy*=0.96;
          p.life-=p.decay; p.rot+=p.rotV;
          if (p.life > 0) {
            if(p.isStar){
              ctx.save(); ctx.translate(p.x,p.y); ctx.rotate(p.rot);
              const s=p.r*3.5*p.life;
              ctx.beginPath();
              ctx.moveTo(0,-s);ctx.bezierCurveTo(s*.13,-s*.13,s*.13,-s*.13,s,0);
              ctx.bezierCurveTo(s*.13,s*.13,s*.13,s*.13,0,s);
              ctx.bezierCurveTo(-s*.13,s*.13,-s*.13,s*.13,-s,0);
              ctx.bezierCurveTo(-s*.13,-s*.13,-s*.13,-s*.13,0,-s);
              ctx.closePath();
              ctx.fillStyle=p.col+Math.floor(p.life*200).toString(16).padStart(2,'0'); ctx.fill();
              ctx.restore();
            } else {
              ctx.beginPath(); ctx.arc(p.x,p.y,p.r*p.life,0,Math.PI*2);
              ctx.fillStyle=p.col+Math.floor(p.life*200).toString(16).padStart(2,'0'); ctx.fill();
            }
          }
        });
        burstP.splice(0,burstP.length,...burstP.filter(p=>p.life>0));

        if(endT === 80) {
            const rc = document.getElementById('ready-card');
            if(rc) rc.classList.add('show');
        }
        
        // Approx 2-3 seconds after animation finishes, call onComplete
        if(endT === 260) {
            if(onComplete) onComplete();
        }
      }

      raf=requestAnimationFrame(draw);
    }

    draw();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', setSize);
    };
  }, [onComplete]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm transition-opacity">
      <div className="w-full max-w-4xl h-[540px] bg-white rounded-2xl shadow-2xl overflow-hidden relative">
        <style>{`
          #stage{width:100%;height:100%;position:relative;overflow:hidden;}
          canvas{position:absolute;inset:0;width:100%;height:100%;}
          
          #hud{
            position:absolute;inset:0;pointer-events:none;z-index:20;
            display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
            padding-bottom:38px;
          }
          #phase-row{
            display:flex;align-items:center;gap:10px;margin-bottom:10px;
            opacity:0;transition:opacity 0.5s;
          }
          #phase-row.in{opacity:1;}
          #phase-dot{width:7px;height:7px;border-radius:50%;background:#1a56ff;animation:pdot 1.2s infinite;}
          @keyframes pdot{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.3;transform:scale(1.5);}}
          #phase-txt{font-size:10px;letter-spacing:0.18em;color:#1a56ff;text-transform:uppercase;font-family:'Courier New',monospace;}
          #main-txt{font-size:22px;font-weight:700;color:#0f172a;margin-bottom:5px;opacity:0;transform:translateY(6px);transition:opacity 0.4s,transform 0.4s;text-align:center;}
          #main-txt.in{opacity:1;transform:translateY(0);}
          #sub-txt{font-size:12px;color:#64748b;opacity:0;transition:opacity 0.4s;text-align:center;}
          #sub-txt.in{opacity:1;}
          
          #bar-wrap{position:absolute;bottom:14px;left:50%;transform:translateX(-50%);width:240px;z-index:20;pointer-events:none;opacity:1;transition:opacity 0.4s;}
          #bar-track{height:2px;background:#e5e8ef;border-radius:2px;overflow:hidden;}
          #bar-fill{height:100%;width:0%;background:linear-gradient(90deg,#1a56ff,#10b981);border-radius:2px;transition:width 0.1s;}
          #bar-pct{font-size:10px;color:#94a3b8;text-align:center;margin-top:6px;font-family:'Courier New',monospace;}
          
          #ready-card{
            position:absolute;inset:0;z-index:40;
            display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;
            background:rgba(255,255,255,0);opacity:0;pointer-events:none;
            transition:opacity 0.8s,background 0.8s;
          }
          #ready-card.show{opacity:1;background:rgba(255,255,255,0.97);}
          .ri{width:68px;height:68px;background:#eff6ff;border:2px solid #1a56ff;border-radius:16px;
            display:flex;align-items:center;justify-content:center;font-size:28px;margin-bottom:8px;}
          .rt{font-size:24px;font-weight:700;color:#0f172a;}
          .rs{font-size:13px;color:#64748b;margin-bottom:18px;}
        `}</style>
        
        <div id="stage">
          <canvas id="cv"></canvas>
        
          <div id="hud">
            <div id="phase-row"><div id="phase-dot"></div><div id="phase-txt">compiling</div></div>
            <div id="main-txt">Compiling your agent</div>
            <div id="sub-txt">Drawing system architecture...</div>
          </div>
        
          <div id="bar-wrap">
            <div id="bar-track"><div id="bar-fill"></div></div>
            <div id="bar-pct">0%</div>
          </div>
        
          <div id="ready-card">
            <div className="ri">✦</div>
            <div className="rt">Agent Deployed</div>
            <div className="rs">Your Meridian AI agent is live and operational</div>
          </div>
        </div>
      </div>
    </div>
  );
}
