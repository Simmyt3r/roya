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
