

(function initNavigation(){
  const toggle=document.querySelector('[data-nav-toggle]');
  const nav=document.querySelector('[data-main-nav]');
  if(toggle&&nav){
    toggle.addEventListener('click',function(){
      const open=nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded',String(open));
    });
    nav.querySelectorAll('a,button').forEach(function(item){
      item.addEventListener('click',function(){
        if(window.innerWidth<=860){
          nav.classList.remove('is-open');
          toggle.setAttribute('aria-expanded','false');
        }
      });
    });
  }

  const logout=document.querySelector('[data-logout]');
  if(logout){
    logout.addEventListener('click',async function(){
      logout.disabled=true;
      try{
        const res=await fetch('/api/v1/auth/logout',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:'{}'
        });
        if(res.ok){window.location.href='/';return;}
      }catch(_error){}
      logout.disabled=false;
    });
  }
})();

const organizationForm=document.querySelector('[data-organization-form]');
if(organizationForm){
  organizationForm.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=organizationForm.querySelector('.form-message');
    const submit=organizationForm.querySelector('button[type="submit"]');
    msg.textContent='Creating your hotel workspace…';
    submit.disabled=true;
    const body=Object.fromEntries(new FormData(organizationForm).entries());
    const res=await fetch('/api/v1/organizations',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Hotel workspace could not be created.';
      submit.disabled=false;
      return;
    }
    window.location.href=(data.data&&data.data.redirect_to)||'/partner';
  });
}

const propertyForm=document.querySelector('[data-property-form]');
if(propertyForm){
  propertyForm.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=propertyForm.querySelector('.form-message');
    const submit=propertyForm.querySelector('button[type="submit"]');
    msg.textContent='Creating property…';
    submit.disabled=true;
    const raw=Object.fromEntries(new FormData(propertyForm).entries());
    Object.keys(raw).forEach(function(key){
      if(raw[key]==='')raw[key]=null;
    });
    const res=await fetch('/api/v1/properties',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(raw)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Property could not be created.';
      submit.disabled=false;
      return;
    }
    window.location.href=(data.data&&data.data.redirect_to)||'/partner#properties';
  });
}


const memberForm=document.querySelector('[data-member-form]');
if(memberForm){
  memberForm.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=memberForm.querySelector('.form-message');
    const submit=memberForm.querySelector('button[type="submit"]');
    const raw=Object.fromEntries(new FormData(memberForm).entries());
    const organizationId=raw.organization_id;
    delete raw.organization_id;
    msg.textContent='Adding team member…';
    submit.disabled=true;
    const res=await fetch('/api/v1/organizations/'+organizationId+'/members',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(raw)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Team member could not be added.';
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });
}

document.querySelectorAll('[data-room-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    const raw=Object.fromEntries(new FormData(form).entries());
    const body={
      property_id:form.dataset.property,
      name:raw.name,
      description:raw.description||'',
      capacity_adults:Number(raw.capacity_adults),
      capacity_children:Number(raw.capacity_children),
      base_occupancy:Number(raw.base_occupancy),
      total_inventory:Number(raw.total_inventory),
      bed_configuration:raw.bed_configuration||''
    };
    msg.textContent='Adding room type…';
    submit.disabled=true;
    const res=await fetch('/api/v1/room-types',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Room type could not be created.';
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });
});

document.querySelectorAll('[data-rate-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    const raw=Object.fromEntries(new FormData(form).entries());
    const price=Number(raw.base_price_ngn);
    const body={
      room_type_id:form.dataset.room,
      name:raw.name,
      base_price_minor:Math.round(price*100),
      currency:'NGN',
      guarantee_type:raw.guarantee_type,
      refundable:new FormData(form).has('refundable'),
      meal_plan:raw.meal_plan,
      deposit_percent:Number(raw.deposit_percent||0),
      min_stay:Number(raw.min_stay||1)
    };
    msg.textContent='Adding rate plan…';
    submit.disabled=true;
    const res=await fetch('/api/v1/rate-plans',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Rate plan could not be created.';
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });
});

function dateRange(startValue,endValue){
  const start=new Date(startValue+'T00:00:00Z');
  const end=new Date(endValue+'T00:00:00Z');
  if(Number.isNaN(start.getTime())||Number.isNaN(end.getTime())||end<start)return [];
  const days=[];
  const cursor=new Date(start);
  while(cursor<=end&&days.length<366){
    days.push(cursor.toISOString().slice(0,10));
    cursor.setUTCDate(cursor.getUTCDate()+1);
  }
  return days;
}

document.querySelectorAll('[data-inventory-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    const raw=Object.fromEntries(new FormData(form).entries());
    const dates=dateRange(raw.start_date,raw.end_date);
    if(!dates.length){
      msg.textContent='Choose a valid inventory date range.';
      return;
    }
    const body={
      room_type_id:form.dataset.room,
      days:dates.map(function(date){
        return {
          date:date,
          total_inventory:Number(raw.total_inventory),
          stop_sell:new FormData(form).has('stop_sell'),
          closed_to_arrival:false,
          closed_to_departure:false,
          min_stay:Number(raw.min_stay||1),
          price_override_minor:null
        };
      })
    };
    msg.textContent='Updating '+dates.length+' inventory day'+(dates.length===1?'':'s')+'…';
    submit.disabled=true;
    const res=await fetch('/api/v1/inventory',{
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Inventory could not be updated.';
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });
});

async function authSubmit(form,mode){
  const msg=form.querySelector('.form-message'); msg.textContent='';
  const body=Object.fromEntries(new FormData(form).entries());
  const res=await fetch('/api/v1/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await res.json().catch(function(){return {};});
  if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Request failed.';return;}
  window.location.href=(data.data&&data.data.redirect_to)||(mode==='login'?'/account':'/');
}
document.querySelectorAll('[data-auth-form]').forEach(function(form){form.addEventListener('submit',function(e){e.preventDefault();authSubmit(form,form.dataset.authForm);});});
if('serviceWorker' in navigator){
  window.addEventListener('load',function(){
    navigator.serviceWorker.register('/static/js/sw.js',{scope:'/'}).catch(function(){});
  });
}

(function initInstallWorkflow(){
  const button=document.querySelector('[data-install-app]');
  if(!button)return;

  let deferredPrompt=null;
  const isStandalone=window.matchMedia('(display-mode: standalone)').matches||window.navigator.standalone===true;
  const isIOS=/iphone|ipad|ipod/i.test(window.navigator.userAgent);

  if(isStandalone)return;

  window.addEventListener('beforeinstallprompt',function(event){
    event.preventDefault();
    deferredPrompt=event;
    button.hidden=false;
  });

  if(isIOS){
    button.hidden=false;
    button.textContent='Add to Home Screen';
  }

  button.addEventListener('click',async function(){
    if(deferredPrompt){
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt=null;
      button.hidden=true;
      return;
    }
    if(isIOS){
      window.alert('On iPhone or iPad: tap Share, then choose “Add to Home Screen”.');
    }
  });

  window.addEventListener('appinstalled',function(){
    deferredPrompt=null;
    button.hidden=true;
  });
})();
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
