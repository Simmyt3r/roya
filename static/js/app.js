async function authSubmit(form,mode){
  const msg=form.querySelector('.form-message'); msg.textContent='';
  const body=Object.fromEntries(new FormData(form).entries());
  const res=await fetch('/api/v1/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await res.json().catch(function(){return {};});
  if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Request failed.';return;}
  window.location.href=mode==='login'?'/partner':'/';
}
document.querySelectorAll('[data-auth-form]').forEach(function(form){form.addEventListener('submit',function(e){e.preventDefault();authSubmit(form,form.dataset.authForm);});});
if('serviceWorker' in navigator){navigator.serviceWorker.register('/static/js/sw.js').catch(function(){});}
const bookingForm=document.getElementById('booking-form');
if(bookingForm){bookingForm.addEventListener('submit',async function(e){
  e.preventDefault(); const msg=bookingForm.querySelector('.form-message'); msg.textContent='Creating a live inventory hold…';
  const f=Object.fromEntries(new FormData(bookingForm).entries());
  const body={property_id:bookingForm.dataset.property,room_type_id:bookingForm.dataset.room,rate_plan_id:bookingForm.dataset.rate,check_in:bookingForm.dataset.checkin,check_out:bookingForm.dataset.checkout,quantity:1,adults:Number(f.adults||1),children:Number(f.children||0),guest_name:f.guest_name,guest_email:f.guest_email,guest_phone:f.guest_phone,guarantee_type:bookingForm.dataset.guarantee};
  const res=await fetch('/api/v1/reservations',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body)});
  const data=await res.json().catch(function(){return {};});
  if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Reservation failed.';return;}
  const r=data.data;
  if(Number(r.amount_due_minor)>0){
    const pay=await fetch('/api/v1/payments/initiate',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({reservation_id:r.reservation_id})});
    const pd=await pay.json().catch(function(){return {};});
    if(pay.ok&&pd.data&&pd.data.authorization_url){window.location.href=pd.data.authorization_url;return;}
    msg.textContent=(pd.error&&pd.error.message)||'Reservation held, but payment could not start.';return;
  }
  window.location.href='/reservation/'+r.reservation_id;
});}


document.querySelectorAll('[data-reservation-approval]').forEach(function(row){
  row.querySelectorAll('[data-reservation-decision]').forEach(function(button){
    button.addEventListener('click',async function(){
      const msg=row.querySelector('.form-message');
      const decision=button.dataset.reservationDecision;
      const reservationId=row.dataset.reservationApproval;
      let reason=null;
      if(decision==='reject'){
        reason=window.prompt('Reason for declining this reservation:','Declined by property');
        if(reason===null)return;
      }
      msg.textContent=decision==='approve'?'Approving reservation…':'Declining reservation…';
      row.querySelectorAll('button').forEach(function(btn){btn.disabled=true;});
      const res=await fetch('/api/v1/partner/reservations/'+reservationId+'/decision',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({decision:decision,reason:reason})
      });
      const data=await res.json().catch(function(){return {};});
      if(!res.ok){
        msg.textContent=(data.error&&data.error.message)||'Reservation decision failed.';
        row.querySelectorAll('button').forEach(function(btn){btn.disabled=false;});
        return;
      }
      msg.textContent=decision==='approve'?'Reservation approved.':'Reservation declined.';
      window.location.reload();
    });
  });
});


(function initLanding(){
  const revealItems=document.querySelectorAll('[data-reveal]');
  if(revealItems.length){
    if('IntersectionObserver' in window && !window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      const observer=new IntersectionObserver(function(entries){
        entries.forEach(function(entry){
          if(entry.isIntersecting){
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },{threshold:0.12,rootMargin:'0px 0px -30px'});
      revealItems.forEach(function(item){observer.observe(item);});
    }else{
      revealItems.forEach(function(item){item.classList.add('is-visible');});
    }
  }

  const form=document.querySelector('[data-home-search]');
  if(form){
    const checkIn=form.querySelector('[data-check-in]');
    const checkOut=form.querySelector('[data-check-out]');
    const formatDate=function(date){
      const y=date.getFullYear();
      const m=String(date.getMonth()+1).padStart(2,'0');
      const d=String(date.getDate()).padStart(2,'0');
      return y+'-'+m+'-'+d;
    };
    const addDays=function(date,days){
      const copy=new Date(date.getFullYear(),date.getMonth(),date.getDate());
      copy.setDate(copy.getDate()+days);
      return copy;
    };
    const today=new Date();
    const tomorrow=addDays(today,1);
    const dayAfter=addDays(today,2);
    const todayValue=formatDate(today);

    if(checkIn){
      checkIn.min=todayValue;
      if(!checkIn.value)checkIn.value=formatDate(tomorrow);
    }
    if(checkOut){
      checkOut.min=checkIn&&checkIn.value?checkIn.value:todayValue;
      if(!checkOut.value)checkOut.value=formatDate(dayAfter);
    }

    if(checkIn&&checkOut){
      checkIn.addEventListener('change',function(){
        const selected=new Date(checkIn.value+'T00:00:00');
        const next=formatDate(addDays(selected,1));
        checkOut.min=next;
        if(!checkOut.value||checkOut.value<=checkIn.value)checkOut.value=next;
      });
    }
  }

  document.querySelectorAll('[data-scroll-top]').forEach(function(link){
    link.addEventListener('click',function(event){
      event.preventDefault();
      window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
    });
  });
})();
