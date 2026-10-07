
(function initSearchLocation(){
  const form=document.querySelector('[data-search-filters]');
  if(!form)return;
  const button=form.querySelector('[data-search-location]');
  const lat=form.querySelector('[data-search-lat]');
  const lng=form.querySelector('[data-search-lng]');
  const city=form.querySelector('input[name="city"]');
  const sort=form.querySelector('[data-search-sort]');
  const distanceOption=form.querySelector('[data-distance-option]');
  const msg=form.querySelector('[data-location-message]');

  if(city){
    city.addEventListener('input',function(){
      if(city.value.trim()){
        if(lat)lat.value='';
        if(lng)lng.value='';
        if(distanceOption)distanceOption.disabled=true;
        if(sort&&sort.value==='distance')sort.value='recommended';
      }
    });
  }

  if(!button)return;
  button.addEventListener('click',function(){
    if(!navigator.geolocation){
      if(msg)msg.textContent='Location search is not supported by this browser.';
      return;
    }
    button.disabled=true;
    if(msg)msg.textContent='Requesting your location…';
    navigator.geolocation.getCurrentPosition(
      function(position){
        if(lat)lat.value=position.coords.latitude.toFixed(6);
        if(lng)lng.value=position.coords.longitude.toFixed(6);
        if(city)city.value='';
        if(distanceOption)distanceOption.disabled=false;
        if(sort)sort.value='distance';
        if(msg)msg.textContent='Location received. Searching nearby hotels…';
        form.submit();
      },
      function(error){
        const messages={
          1:'Location permission was not granted.',
          2:'Your location could not be determined.',
          3:'Location request timed out.'
        };
        if(msg)msg.textContent=messages[error.code]||'Location search could not start.';
        button.disabled=false;
      },
      {enableHighAccuracy:false,timeout:8000,maximumAge:300000}
    );
  });
})();


const inviteAccept=document.querySelector('[data-invite-accept]');
if(inviteAccept){
  inviteAccept.addEventListener('click',async function(){
    const msg=document.querySelector('[data-invite-message]');
    inviteAccept.disabled=true;
    if(msg)msg.textContent='Accepting hotel invitation…';
    const res=await fetch('/api/v1/invites/accept',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:inviteAccept.dataset.inviteToken})
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Invitation could not be accepted.';
      inviteAccept.disabled=false;
      return;
    }
    window.location.href=(data.data&&data.data.redirect_to)||'/partner';
  });
}

document.querySelectorAll('[data-pending-invite]').forEach(function(row){
  const revoke=row.querySelector('[data-invite-revoke]');
  const msg=row.querySelector('.form-message');
  if(!revoke)return;
  revoke.addEventListener('click',async function(){
    if(!window.confirm('Revoke this hotel invitation?'))return;
    revoke.disabled=true;
    if(msg)msg.textContent='Revoking invitation…';
    const res=await fetch('/api/v1/organizations/'+row.dataset.organization+'/invites/'+row.dataset.invite,{
      method:'DELETE'
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Invitation could not be revoked.';
      revoke.disabled=false;
      return;
    }
    row.remove();
  });
});

document.querySelectorAll('[data-admin-integration]').forEach(function(form){
  const provider=form.dataset.adminIntegration;
  const test=form.querySelector('[data-integration-test]');
  const message=form.querySelector('.form-message');
  const endpoint='/api/v1/admin/integrations/'+provider;

  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const submit=form.querySelector('[type="submit"]');
    const body=Object.fromEntries(new FormData(form).entries());
    if(provider==='smtp')body.port=Number(body.port);
    submit.disabled=true;
    message.textContent='Saving settings…';
    try{
      const response=await fetch(endpoint,{
        method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
      });
      const data=await response.json().catch(function(){return {};});
      if(!response.ok){
        message.textContent=(data.error&&data.error.message)||'Settings could not be saved.';
        return;
      }
      form.querySelectorAll('input[type="password"]').forEach(function(input){input.value='';});
      message.textContent='Saved. Run the connection check before use.';
      if(test)test.disabled=false;
    }catch(_error){message.textContent='Connection failed. Please try again.';}
    finally{submit.disabled=false;}
  });

  if(test)test.addEventListener('click',async function(){
    test.disabled=true;
    message.textContent='Checking connection…';
    try{
      const response=await fetch(endpoint+'/test',{
        method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
      });
      const data=await response.json().catch(function(){return {};});
      message.textContent=response.ok?(data.data&&data.data.message)||'Connection succeeded.':
        (data.error&&data.error.message)||'Connection check failed.';
    }catch(_error){message.textContent='Connection check could not complete.';}
    finally{test.disabled=false;}
  });
});


document.querySelectorAll('[data-property-image]').forEach(function(card){
  const save=card.querySelector('[data-image-save]');
  const remove=card.querySelector('[data-image-delete]');
  const msg=card.querySelector('.form-message');

  if(save)save.addEventListener('click',async function(){
    save.disabled=true;
    if(msg)msg.textContent='Saving photo details…';
    const res=await fetch('/api/v1/properties/'+card.dataset.property+'/images/'+card.dataset.image,{
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        alt_text:card.querySelector('[data-image-alt]').value||null,
        sort_order:Number(card.querySelector('[data-image-order]').value||0)
      })
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Photo details could not be saved.';
      save.disabled=false;
      return;
    }
    window.location.reload();
  });

  if(remove)remove.addEventListener('click',async function(){
    if(!window.confirm('Delete this hotel photo?'))return;
    remove.disabled=true;
    if(msg)msg.textContent='Deleting photo…';
    const res=await fetch('/api/v1/properties/'+card.dataset.property+'/images/'+card.dataset.image,{method:'DELETE'});
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Photo could not be deleted.';
      remove.disabled=false;
      return;
    }
    card.remove();
  });
});

document.querySelectorAll('[data-room-photo-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    if(!photoFitsUploadLimit(form,msg))return;
    msg.textContent='Uploading room photo…';
    submit.disabled=true;
    const res=await fetch('/api/v1/room-types/'+form.dataset.room+'/images',{
      method:'POST',
      body:new FormData(form)
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      msg.textContent=(data.error&&data.error.message)||'Room photo could not be uploaded.';
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });
});

document.querySelectorAll('[data-room-image]').forEach(function(card){
  const save=card.querySelector('[data-image-save]');
  const remove=card.querySelector('[data-image-delete]');
  const msg=card.querySelector('.form-message');

  if(save)save.addEventListener('click',async function(){
    save.disabled=true;
    if(msg)msg.textContent='Saving room photo…';
    const res=await fetch('/api/v1/room-types/'+card.dataset.room+'/images/'+card.dataset.image,{
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        alt_text:card.querySelector('[data-image-alt]').value||null,
        sort_order:Number(card.querySelector('[data-image-order]').value||0)
      })
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Room photo details could not be saved.';
      save.disabled=false;
      return;
    }
    window.location.reload();
  });

  if(remove)remove.addEventListener('click',async function(){
    if(!window.confirm('Delete this room photo?'))return;
    remove.disabled=true;
    if(msg)msg.textContent='Deleting room photo…';
    const res=await fetch('/api/v1/room-types/'+card.dataset.room+'/images/'+card.dataset.image,{method:'DELETE'});
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Room photo could not be deleted.';
      remove.disabled=false;
      return;
    }
    card.remove();
  });
});


document.querySelectorAll('[data-notification-id]').forEach(function(card){
  const button=card.querySelector('[data-notification-read]');
  const open=card.querySelector('[data-notification-open]');
  async function markRead(){
    if(!card.classList.contains('notification-unread'))return true;
    const res=await fetch('/api/v1/notifications/'+card.dataset.notificationId+'/read',{
      method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
    });
    if(res.ok){
      card.classList.remove('notification-unread');
      if(button)button.remove();
      return true;
    }
    return false;
  }
  if(button)button.addEventListener('click',markRead);
  if(open)open.addEventListener('click',function(){markRead();});
});
const readAll=document.querySelector('[data-read-all-notifications]');
if(readAll){
  readAll.addEventListener('click',async function(){
    readAll.disabled=true;
    const res=await fetch('/api/v1/notifications/read-all',{
      method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
    });
    if(res.ok)window.location.reload();
    else readAll.disabled=false;
  });
}


document.querySelectorAll('[data-team-member]').forEach(function(row){
  const save=row.querySelector('[data-team-save]');
  const statusButton=row.querySelector('[data-team-status]');
  const roleSelect=row.querySelector('[data-team-role]');
  const msg=row.querySelector('.team-message');
  if(!save||!roleSelect)return;

  async function updateTeam(status){
    row.querySelectorAll('button,select').forEach(function(el){el.disabled=true;});
    if(msg)msg.textContent='Updating hotel access…';
    const res=await fetch('/api/v1/organizations/'+row.dataset.organization+'/members/'+row.dataset.user,{
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({role:roleSelect.value,status:status})
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      if(msg)msg.textContent=(data.error&&data.error.message)||'Team access could not be updated.';
      row.querySelectorAll('button,select').forEach(function(el){el.disabled=false;});
      return;
    }
    window.location.reload();
  }

  save.addEventListener('click',function(){
    const currentStatus=statusButton&&statusButton.dataset.teamStatus==='active'?'suspended':'active';
    updateTeam(currentStatus);
  });

  if(statusButton){
    statusButton.addEventListener('click',function(){
      const next=statusButton.dataset.teamStatus;
      const verb=next==='suspended'?'Suspend':'Restore';
      if(!window.confirm(verb+' this hotel team member?'))return;
      updateTeam(next);
    });
  }
});


document.querySelectorAll('[data-refund-request]').forEach(function(button){
  button.addEventListener('click',async function(){
    const msg=document.querySelector('[data-reservation-message]');const reason=window.prompt('Reason for cancellation and refund:','Plans changed');if(reason===null)return;button.disabled=true;if(msg)msg.textContent='Submitting refund request…';
    const res=await fetch('/api/v1/refunds',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reservation_id:button.dataset.refundRequest,reason:reason})});
    const data=await res.json().catch(function(){return {};});if(!res.ok){if(msg)msg.textContent=(data.error&&data.error.message)||'Refund request could not be submitted.';button.disabled=false;return;}window.location.reload();
  });
});
document.querySelectorAll('[data-refund-process]').forEach(function(button){
  button.addEventListener('click',async function(){
    if(!window.confirm('Initiate this refund through Paystack?'))return;button.disabled=true;
    const res=await fetch('/api/v1/partner/refunds/'+button.dataset.refundProcess+'/process',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const data=await res.json().catch(function(){return {};});if(!res.ok){window.alert((data.error&&data.error.message)||'Refund could not be initiated.');button.disabled=false;return;}window.location.reload();
  });
});


document.querySelectorAll('[data-room-edit-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');const raw=Object.fromEntries(new FormData(form).entries());const body={name:raw.name,description:raw.description||'',capacity_adults:Number(raw.capacity_adults),capacity_children:Number(raw.capacity_children),base_occupancy:Number(raw.base_occupancy),total_inventory:Number(raw.total_inventory),bed_configuration:raw.bed_configuration||'',status:raw.status};msg.textContent='Saving room type…';submit.disabled=true;
    const res=await fetch('/api/v1/room-types/'+form.dataset.room,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Room type could not be saved.';submit.disabled=false;return;}window.location.reload();
  });
});
document.querySelectorAll('[data-rate-edit-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');const raw=Object.fromEntries(new FormData(form).entries());const body={name:raw.name,base_price_minor:Math.round(Number(raw.base_price_ngn)*100),currency:'NGN',guarantee_type:raw.guarantee_type,refundable:new FormData(form).has('refundable'),meal_plan:raw.meal_plan||'room_only',deposit_percent:Number(raw.deposit_percent||0),min_stay:Number(raw.min_stay||1),free_cancellation_hours:Number(raw.free_cancellation_hours||24),status:raw.status};msg.textContent='Saving rate plan…';submit.disabled=true;
    const res=await fetch('/api/v1/rate-plans/'+form.dataset.rate,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Rate plan could not be saved.';submit.disabled=false;return;}window.location.reload();
  });
});


document.querySelectorAll('[data-reservation-status]').forEach(function(button){
  button.addEventListener('click',async function(){
    const target=button.dataset.reservationStatus;
    const label=target.replace('_',' ');
    if(!window.confirm('Mark this reservation as '+label+'?'))return;
    button.disabled=true;
    const res=await fetch('/api/v1/partner/reservations/'+button.dataset.reservationId+'/status',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status:target})
    });
    const data=await res.json().catch(function(){return {};});
    if(!res.ok){
      window.alert((data.error&&data.error.message)||'Reservation status could not be updated.');
      button.disabled=false;
      return;
    }
    window.location.reload();
  });
});


document.querySelectorAll('[data-profile-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');const body=Object.fromEntries(new FormData(form).entries());if(!body.phone)body.phone=null;msg.textContent='Saving profile…';submit.disabled=true;
    const res=await fetch('/api/v1/auth/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Profile could not be saved.';submit.disabled=false;return;}msg.textContent='Profile saved.';submit.disabled=false;
  });
});
function photoFitsUploadLimit(form,msg){
  const file=form.querySelector('input[type="file"]')?.files?.[0];
  if(file&&file.size>4*1024*1024){
    msg.textContent='Image must be 4 MB or smaller.';
    return false;
  }
  return true;
}

document.querySelectorAll('[data-property-photo-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');if(!photoFitsUploadLimit(form,msg))return;const data=new FormData(form);msg.textContent='Uploading photo…';submit.disabled=true;
    const res=await fetch('/api/v1/properties/'+form.dataset.property+'/images',{method:'POST',body:data});
    const body=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(body.error&&body.error.message)||'Photo could not be uploaded.';submit.disabled=false;return;}msg.textContent='Photo uploaded.';window.location.reload();
  });
});


document.querySelectorAll('[data-property-details-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');const body=Object.fromEntries(new FormData(form).entries());if(!body.phone)body.phone=null;if(!body.email)body.email=null;msg.textContent='Saving property details…';submit.disabled=true;
    const res=await fetch('/api/v1/properties/'+form.dataset.property,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Property details could not be saved.';submit.disabled=false;return;}msg.textContent=data.data&&data.data.requires_reverification?'Saved. Identity/location changes require verification again.':'Property details saved.';window.setTimeout(function(){window.location.reload();},500);
  });
});
document.querySelectorAll('[data-amenities-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();const msg=form.querySelector('.form-message');const submit=form.querySelector('button[type="submit"]');const codes=Array.from(form.querySelectorAll('input[name="amenities"]:checked')).map(function(input){return input.value;});msg.textContent='Saving amenities…';submit.disabled=true;
    const res=await fetch('/api/v1/properties/'+form.dataset.property+'/amenities',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({codes:codes})});
    const data=await res.json().catch(function(){return {};});if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Amenities could not be saved.';submit.disabled=false;return;}msg.textContent='Amenities saved.';submit.disabled=false;
  });
});


document.querySelectorAll('[data-pay-reservation]').forEach(function(button){button.addEventListener('click',async function(){const msg=document.querySelector('[data-reservation-message]');button.disabled=true;if(msg)msg.textContent='Starting secure payment…';const res=await fetch('/api/v1/payments/initiate',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':'payment-'+button.dataset.payReservation},body:JSON.stringify({reservation_id:button.dataset.payReservation})});const data=await res.json().catch(function(){return {};});if(res.ok&&data.data&&data.data.authorization_url){window.location.href=data.data.authorization_url;return;}if(msg)msg.textContent=(data.error&&data.error.message)||'Payment could not be started.';button.disabled=false;});});
document.querySelectorAll('[data-cancel-reservation]').forEach(function(button){button.addEventListener('click',async function(){const msg=document.querySelector('[data-reservation-message]');const reason=window.prompt('Why are you cancelling this reservation?','Plans changed');if(reason===null)return;button.disabled=true;if(msg)msg.textContent='Cancelling reservation…';const res=await fetch('/api/v1/reservations/'+button.dataset.cancelReservation+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:reason})});const data=await res.json().catch(function(){return {};});if(!res.ok){if(msg)msg.textContent=(data.error&&data.error.message)||'Reservation could not be cancelled.';button.disabled=false;return;}window.location.reload();});});
document.querySelectorAll('[data-property-verification]').forEach(function(row){row.querySelectorAll('[data-verification-status]').forEach(function(button){button.addEventListener('click',async function(){const msg=row.querySelector('.form-message');const status=button.dataset.verificationStatus;const notes=status==='verified'?null:window.prompt('Verification note:','');if(status!=='verified'&&notes===null)return;row.querySelectorAll('button').forEach(function(item){item.disabled=true;});if(msg)msg.textContent='Updating verification…';const res=await fetch('/api/v1/admin/properties/'+row.dataset.propertyVerification+'/verification',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:status,notes:notes})});const data=await res.json().catch(function(){return {};});if(!res.ok){if(msg)msg.textContent=(data.error&&data.error.message)||'Verification update failed.';row.querySelectorAll('button').forEach(function(item){item.disabled=false;});return;}window.location.reload();});});});



(function initNavigation(){
  const toggle=document.querySelector('[data-nav-toggle]');
  const nav=document.querySelector('[data-main-nav]');
  const closeButton=document.querySelector('[data-nav-close]');
  if(toggle&&nav){
    const closeNav=function(){
      nav.classList.remove('is-open');
      toggle.classList.remove('is-open');
      toggle.setAttribute('aria-expanded','false');
      toggle.setAttribute('aria-label','Open menu');
      document.body.classList.remove('mobile-nav-open');
    };
    const openNav=function(){
      nav.classList.add('is-open');
      toggle.classList.add('is-open');
      toggle.setAttribute('aria-expanded','true');
      toggle.setAttribute('aria-label','Close menu');
      document.body.classList.add('mobile-nav-open');
    };

    toggle.addEventListener('click',function(event){
      event.preventDefault();
      event.stopPropagation();
      if(nav.classList.contains('is-open'))closeNav();
      else openNav();
    });

    if(closeButton){
      closeButton.addEventListener('click',function(event){
        event.preventDefault();
        event.stopPropagation();
        closeNav();
        toggle.focus({preventScroll:true});
      });
    }

    nav.querySelectorAll('a,button').forEach(function(item){
      item.addEventListener('click',function(){
        if(window.innerWidth<=860)closeNav();
      });
    });

    document.addEventListener('keydown',function(event){
      if(event.key==='Escape'&&nav.classList.contains('is-open')){
        closeNav();
        toggle.focus();
      }
    });

    document.addEventListener('pointerdown',function(event){
      if(window.innerWidth>860||!nav.classList.contains('is-open'))return;
      if(nav.contains(event.target)||toggle.contains(event.target))return;
      closeNav();
    });

    window.addEventListener('resize',function(){
      if(window.innerWidth>860)closeNav();
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
    window.location.href=(data.data&&data.data.redirect_to)||'/partner/rooms';
  });
}


const memberForm=document.querySelector('[data-member-form]');
if(memberForm){
  memberForm.addEventListener('submit',async function(event){
    event.preventDefault();
    const msg=memberForm.querySelector('.form-message');
    const submit=memberForm.querySelector('button[type="submit"]');
    const inviteResult=memberForm.querySelector('[data-invite-result]');
    const inviteLink=memberForm.querySelector('[data-invite-link]');
    const raw=Object.fromEntries(new FormData(memberForm).entries());
    const organizationId=raw.organization_id;
    delete raw.organization_id;
    if(inviteResult)inviteResult.hidden=true;
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
    if(data.data&&data.data.invited){
      msg.textContent='Invitation created. Copy the one-time link below.';
      if(inviteLink)inviteLink.value=data.data.invite_url||'';
      if(inviteResult)inviteResult.hidden=false;
      submit.disabled=false;
      return;
    }
    window.location.reload();
  });

  const copyButton=memberForm.querySelector('[data-copy-invite]');
  if(copyButton){
    copyButton.addEventListener('click',async function(){
      const inviteLink=memberForm.querySelector('[data-invite-link]');
      if(!inviteLink||!inviteLink.value)return;
      try{
        await navigator.clipboard.writeText(inviteLink.value);
        copyButton.textContent='Copied';
      }catch(_error){
        inviteLink.select();
        document.execCommand('copy');
        copyButton.textContent='Copied';
      }
    });
  }
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
      min_stay:Number(raw.min_stay||1),
      free_cancellation_hours:Number(raw.free_cancellation_hours||24)
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
function requestKey(prefix){
  if(window.crypto&&typeof window.crypto.randomUUID==='function')return prefix+'-'+window.crypto.randomUUID();
  return prefix+'-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
}

const bookingForm=document.getElementById('booking-form');
if(bookingForm){
  const reservationKey=requestKey('reservation');
  const submit=bookingForm.querySelector('button[type="submit"]');
  let bookingBusy=false;
  bookingForm.addEventListener('submit',async function(e){
    e.preventDefault();
    if(bookingBusy)return;
    bookingBusy=true;
    if(submit)submit.disabled=true;
    const msg=bookingForm.querySelector('.form-message');
    msg.textContent='Checking availability and reserving your room…';
    const f=Object.fromEntries(new FormData(bookingForm).entries());
    const body={property_id:bookingForm.dataset.property,room_type_id:bookingForm.dataset.room,rate_plan_id:bookingForm.dataset.rate,check_in:bookingForm.dataset.checkin,check_out:bookingForm.dataset.checkout,quantity:1,adults:Number(f.adults||1),children:Number(f.children||0),guest_name:f.guest_name,guest_email:f.guest_email,guest_phone:f.guest_phone,guarantee_type:bookingForm.dataset.guarantee};
    try{
      const res=await fetch('/api/v1/reservations',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':reservationKey},body:JSON.stringify(body)});
      const data=await res.json().catch(function(){return {};});
      if(!res.ok){msg.textContent=(data.error&&data.error.message)||'Reservation failed.';return;}
      const r=data.data;
      if(Number(r.amount_due_minor)>0){
        const paymentKey='payment-'+r.reservation_id;
        const pay=await fetch('/api/v1/payments/initiate',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':paymentKey},body:JSON.stringify({reservation_id:r.reservation_id})});
        const pd=await pay.json().catch(function(){return {};});
        if(pay.ok&&pd.data&&pd.data.authorization_url){window.location.href=pd.data.authorization_url;return;}
        msg.textContent=(pd.error&&pd.error.message)||'Your room is reserved, but payment could not start. Open My stays to continue.';
        return;
      }
      window.location.href='/reservation/'+r.reservation_id;
    }catch(_error){
      msg.textContent='The booking could not complete. You can retry safely.';
    }finally{
      bookingBusy=false;
      if(submit)submit.disabled=false;
    }
  });
}


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


(function initAdminEmailWorkspace(){
  const dataNode=document.getElementById('admin-email-template-data');
  const campaignForm=document.querySelector('[data-email-campaign]');
  const templateForm=document.querySelector('[data-email-template-form]');
  if(!dataNode||(!campaignForm&&!templateForm))return;

  let templates=[];
  try{templates=JSON.parse(dataNode.textContent||'[]');}catch(_error){templates=[];}
  const byId=new Map(templates.map(function(item){return [String(item.id),item];}));

  function applyTemplate(form,item){
    if(!form||!item)return;
    const subject=form.querySelector('[name="subject"]');
    const body=form.querySelector('[name="body"]');
    if(subject)subject.value=item.subject||'';
    if(body)body.value=item.body||'';
  }

  if(campaignForm){
    const templateSelect=campaignForm.querySelector('[data-email-template-select]');
    const audience=campaignForm.querySelector('[data-email-audience]');
    const customWrap=campaignForm.querySelector('[data-custom-email-wrap]');
    const message=campaignForm.querySelector('.form-message');

    function syncAudience(){
      const custom=audience&&audience.value==='custom';
      if(customWrap)customWrap.hidden=!custom;
      const field=customWrap&&customWrap.querySelector('textarea');
      if(field)field.required=Boolean(custom);
    }

    if(templateSelect)templateSelect.addEventListener('change',function(){
      applyTemplate(campaignForm,byId.get(String(templateSelect.value)));
    });
    if(audience){
      audience.addEventListener('change',syncAudience);
      syncAudience();
    }

    campaignForm.addEventListener('submit',async function(event){
      event.preventDefault();
      const submit=campaignForm.querySelector('[type="submit"]');
      const raw=Object.fromEntries(new FormData(campaignForm).entries());
      const custom=String(raw.custom_recipients||'')
        .split(/[\s,;]+/)
        .map(function(value){return value.trim();})
        .filter(Boolean);
      const audienceLabel=audience&&audience.options[audience.selectedIndex]?
        audience.options[audience.selectedIndex].text:'selected audience';
      if(!window.confirm('Queue this email for '+audienceLabel+'?'))return;

      const payload={
        audience:raw.audience,
        subject:raw.subject,
        body:raw.body,
        template_id:raw.template_id||null,
        custom_recipients:raw.audience==='custom'?custom:[]
      };
      submit.disabled=true;
      message.textContent='Queueing campaign…';
      try{
        const response=await fetch('/api/v1/admin/email/campaigns',{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          message.textContent=(data.error&&data.error.message)||'Campaign could not be queued.';
          return;
        }
        const result=data.data||{};
        const immediate=result.immediate_delivery||{};
        message.textContent='Queued '+(result.queued||0)+' recipient(s). '+
          (immediate.sent||0)+' sent immediately; remaining messages stay in the retry queue.';
        setTimeout(function(){window.location.reload();},1200);
      }catch(_error){
        message.textContent='Campaign request could not complete.';
      }finally{
        submit.disabled=false;
      }
    });
  }

  if(templateForm){
    const editSelect=templateForm.querySelector('[data-email-template-edit]');
    const idField=templateForm.querySelector('[name="template_id"]');
    const deleteButton=templateForm.querySelector('[data-email-template-delete]');
    const newButton=templateForm.querySelector('[data-email-template-new]');
    const message=templateForm.querySelector('.form-message');

    function resetTemplateForm(){
      templateForm.reset();
      idField.value='';
      if(editSelect)editSelect.value='';
      if(deleteButton)deleteButton.hidden=true;
      message.textContent='';
    }

    function loadTemplate(){
      const item=byId.get(String(editSelect.value));
      if(!item){resetTemplateForm();return;}
      idField.value=String(item.id);
      templateForm.querySelector('[name="name"]').value=item.name||'';
      templateForm.querySelector('[name="category"]').value=item.category||'marketing';
      applyTemplate(templateForm,item);
      deleteButton.hidden=false;
    }

    if(editSelect)editSelect.addEventListener('change',loadTemplate);
    if(newButton)newButton.addEventListener('click',resetTemplateForm);

    templateForm.addEventListener('submit',async function(event){
      event.preventDefault();
      const submit=templateForm.querySelector('[type="submit"]');
      const raw=Object.fromEntries(new FormData(templateForm).entries());
      const id=raw.template_id;
      const endpoint=id?'/api/v1/admin/email/templates/'+id:'/api/v1/admin/email/templates';
      submit.disabled=true;
      message.textContent=id?'Updating template…':'Creating template…';
      try{
        const response=await fetch(endpoint,{
          method:id?'PUT':'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({name:raw.name,category:raw.category,subject:raw.subject,body:raw.body})
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          message.textContent=(data.error&&data.error.message)||'Template could not be saved.';
          return;
        }
        message.textContent='Template saved.';
        setTimeout(function(){window.location.reload();},700);
      }catch(_error){
        message.textContent='Template request could not complete.';
      }finally{
        submit.disabled=false;
      }
    });

    if(deleteButton)deleteButton.addEventListener('click',async function(){
      const id=idField.value;
      if(!id||!window.confirm('Archive this email template?'))return;
      deleteButton.disabled=true;
      message.textContent='Archiving template…';
      try{
        const response=await fetch('/api/v1/admin/email/templates/'+id,{method:'DELETE'});
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          message.textContent=(data.error&&data.error.message)||'Template could not be archived.';
          return;
        }
        window.location.reload();
      }catch(_error){
        message.textContent='Template request could not complete.';
      }finally{
        deleteButton.disabled=false;
      }
    });
  }


  const consentForm=document.querySelector('[data-marketing-consent]');
  if(consentForm)consentForm.addEventListener('submit',async function(event){
    event.preventDefault();
    const submit=consentForm.querySelector('[type="submit"]');
    const message=consentForm.querySelector('.form-message');
    const raw=Object.fromEntries(new FormData(consentForm).entries());
    if(raw.consent_confirmed!=='true'){
      message.textContent='Confirm explicit marketing consent before saving.';
      return;
    }
    submit.disabled=true;
    message.textContent='Recording consent…';
    try{
      const response=await fetch('/api/v1/admin/email/subscribers',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email:raw.email,consent_confirmed:true})
      });
      const data=await response.json().catch(function(){return {};});
      if(!response.ok){
        message.textContent=(data.error&&data.error.message)||'Marketing consent could not be recorded.';
        return;
      }
      message.textContent='Marketing consent recorded.';
      setTimeout(function(){window.location.reload();},700);
    }catch(_error){
      message.textContent='Consent request could not complete.';
    }finally{
      submit.disabled=false;
    }
  });

  document.querySelectorAll('[data-marketing-subscriber]').forEach(function(row){
    const suppress=row.querySelector('[data-marketing-suppress]');
    const message=row.querySelector('.form-message');
    if(!suppress)return;
    suppress.addEventListener('click',async function(){
      if(!window.confirm('Stop marketing email for this subscriber?'))return;
      suppress.disabled=true;
      if(message)message.textContent='Suppressing marketing email…';
      try{
        const response=await fetch('/api/v1/admin/email/subscribers/'+row.dataset.marketingSubscriber,{
          method:'DELETE'
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Subscriber could not be suppressed.';
          return;
        }
        if(message)message.textContent='Marketing email suppressed.';
        setTimeout(function(){window.location.reload();},500);
      }catch(_error){
        if(message)message.textContent='Subscriber update could not complete.';
      }finally{
        suppress.disabled=false;
      }
    });
  });

  const deliver=document.querySelector('[data-email-deliver]');
  const deliverMessage=document.querySelector('[data-email-deliver-message]');
  if(deliver)deliver.addEventListener('click',async function(){
    deliver.disabled=true;
    if(deliverMessage)deliverMessage.textContent='Processing up to 50 queued emails…';
    try{
      const response=await fetch('/api/v1/admin/email/deliver',{
        method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
      });
      const data=await response.json().catch(function(){return {};});
      const result=data.data||{};
      if(deliverMessage)deliverMessage.textContent=response.ok?
        'Checked '+(result.checked||0)+': '+(result.sent||0)+' sent, '+(result.retrying||0)+' retrying, '+(result.failed||0)+' failed, '+(result.suppressed||0)+' suppressed.':
        (data.error&&data.error.message)||'Queued email could not be processed.';
    }catch(_error){
      if(deliverMessage)deliverMessage.textContent='Queue processing could not complete.';
    }finally{
      deliver.disabled=false;
    }
  });
})();


(function initAdminOperations(){
  const section=document.querySelector('.admin-operations');
  if(!section)return;
  const message=section.querySelector('[data-ops-message]');
  const buttons=section.querySelectorAll('[data-ops-action]');

  function setBusy(value){
    buttons.forEach(function(button){button.disabled=value;});
  }

  buttons.forEach(function(button){
    button.addEventListener('click',async function(){
      const action=button.dataset.opsAction;
      if(action==='refresh'){
        window.location.reload();
        return;
      }
      const endpoint=action==='reconcile-money'?
        '/api/v1/admin/operations/reconcile-money':
        action==='scan-alerts'?
          '/api/v1/admin/operations/scan':
          '/api/v1/admin/operations/expire-holds';
      setBusy(true);
      if(message)message.textContent=action==='reconcile-money'?
        'Reconciling pending payments and refunds…':
        action==='scan-alerts'?
          'Running recovery and anomaly scan…':
          'Expiring overdue reservation holds…';
      try{
        const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Operation could not complete.';
          return;
        }
        if(action==='reconcile-money'){
          const result=data.data||{};
          const payments=result.payments||{};
          const refunds=result.refunds||{};
          if(message)message.textContent=
            'Payments: '+(payments.reconciled||0)+' reconciled, '+(payments.errors||0)+' errors. '+
            'Refunds: '+(refunds.processed||0)+' processed, '+(refunds.failed||0)+' failed, '+(refunds.errors||0)+' errors.';
        }else if(action==='scan-alerts'){
          const result=data.data||{};
          if(message)message.textContent=
            'Scan complete: '+(result.new_alerts||0)+' new, '+(result.reopened_alerts||0)+
            ' reopened, '+(result.resolved_alerts||0)+' resolved.';
        }else{
          if(message)message.textContent='Expired '+((data.data&&data.data.expired)||0)+' overdue hold(s).';
        }
        setTimeout(function(){window.location.reload();},900);
      }catch(_error){
        if(message)message.textContent='Operational recovery request could not complete.';
      }finally{
        setBusy(false);
      }
    });
  });

  section.querySelectorAll('[data-operational-alert]').forEach(function(row){
    const button=row.querySelector('[data-alert-ack]');
    const message=row.querySelector('.form-message');
    if(!button)return;
    button.addEventListener('click',async function(){
      button.disabled=true;
      if(message)message.textContent='Acknowledging incident…';
      try{
        const response=await fetch('/api/v1/admin/operations/alerts/'+row.dataset.operationalAlert+'/acknowledge',{
          method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Incident could not be acknowledged.';
          return;
        }
        if(message)message.textContent='Incident acknowledged.';
        setTimeout(function(){window.location.reload();},500);
      }catch(_error){
        if(message)message.textContent='Incident update could not complete.';
      }finally{
        button.disabled=false;
      }
    });
  });

})();


(function initGuestReview(){
  const form=document.querySelector('[data-review-form]');
  if(!form)return;
  const message=form.querySelector('.form-message');
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const submit=form.querySelector('[type="submit"]');
    const raw=Object.fromEntries(new FormData(form).entries());
    submit.disabled=true;
    if(message)message.textContent='Publishing your verified review…';
    try{
      const response=await fetch('/api/v1/reviews',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          reservation_id:raw.reservation_id,
          rating:Number(raw.rating),
          comment:raw.comment||''
        })
      });
      const data=await response.json().catch(function(){return {};});
      if(!response.ok){
        if(message)message.textContent=(data.error&&data.error.message)||'Review could not be published.';
        return;
      }
      if(message)message.textContent='Review published. Thank you.';
      setTimeout(function(){window.location.reload();},650);
    }catch(_error){
      if(message)message.textContent='Review request could not complete.';
    }finally{
      submit.disabled=false;
    }
  });
})();


(function initAdminUserAccounts(){
  document.querySelectorAll('[data-admin-user]').forEach(function(row){
    const buttons=row.querySelectorAll('[data-user-status]');
    const message=row.querySelector('.form-message');
    buttons.forEach(function(button){
      button.addEventListener('click',async function(){
        const status=button.dataset.userStatus;
        const verb=status==='suspended'?'suspend':'reactivate';
        if(!window.confirm('Are you sure you want to '+verb+' this account?'))return;
        buttons.forEach(function(item){item.disabled=true;});
        if(message)message.textContent=status==='suspended'?
          'Suspending account and revoking sessions…':'Reactivating account…';
        try{
          const response=await fetch('/api/v1/admin/users/'+row.dataset.adminUser+'/status',{
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({status:status})
          });
          const data=await response.json().catch(function(){return {};});
          if(!response.ok){
            if(message)message.textContent=(data.error&&data.error.message)||'Account status could not be changed.';
            return;
          }
          if(message)message.textContent=status==='suspended'?
            'Account suspended and active iRoya sessions revoked.':'Account reactivated.';
          setTimeout(function(){window.location.reload();},600);
        }catch(_error){
          if(message)message.textContent='Account status request could not complete.';
        }finally{
          buttons.forEach(function(item){item.disabled=false;});
        }
      });
    });


    const roleSelect=row.querySelector('[data-platform-role]');
    const roleSave=row.querySelector('[data-platform-role-save]');
    if(roleSelect&&roleSave){
      roleSave.addEventListener('click',async function(){
        const platformRole=roleSelect.value;
        if(!window.confirm('Change this user\'s platform access to '+platformRole+'? Their active iRoya sessions will be revoked.'))return;
        roleSave.disabled=true;
        if(message)message.textContent='Updating platform access…';
        try{
          const response=await fetch('/api/v1/admin/users/'+row.dataset.adminUser+'/platform-role',{
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({platform_role:platformRole})
          });
          const data=await response.json().catch(function(){return {};});
          if(!response.ok){
            if(message)message.textContent=(data.error&&data.error.message)||'Platform role could not be changed.';
            return;
          }
          if(message)message.textContent='Platform role updated. Active sessions were revoked.';
          setTimeout(function(){window.location.reload();},650);
        }catch(_error){
          if(message)message.textContent='Platform role request could not complete.';
        }finally{
          roleSave.disabled=false;
        }
      });
    }
  });
})();


(function initAdminReviews(){
  document.querySelectorAll('[data-admin-review]').forEach(function(row){
    const button=row.querySelector('[data-review-visibility]');
    const message=row.querySelector('.form-message');
    if(!button)return;
    button.addEventListener('click',async function(){
      const isVisible=button.dataset.reviewVisibility==='true';
      const verb=isVisible?'restore':'hide';
      if(!window.confirm('Are you sure you want to '+verb+' this review?'))return;
      button.disabled=true;
      if(message)message.textContent=isVisible?'Restoring review…':'Hiding review…';
      try{
        const response=await fetch('/api/v1/admin/reviews/'+row.dataset.adminReview+'/visibility',{
          method:'PUT',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({is_visible:isVisible})
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Review visibility could not be changed.';
          return;
        }
        if(message)message.textContent=isVisible?'Review restored to public listings.':'Review hidden from public listings.';
        setTimeout(function(){window.location.reload();},600);
      }catch(_error){
        if(message)message.textContent='Review moderation request could not complete.';
      }finally{
        button.disabled=false;
      }
    });
  });
})();


(function initHotelMiniDomain(){
  const form=document.querySelector('[data-mini-domain-form]');
  if(form){
    const message=form.querySelector('.form-message');
    form.addEventListener('submit',async function(event){
      event.preventDefault();
      const button=form.querySelector('[type="submit"]');
      const value=(new FormData(form).get('mini_domain')||'').toString();
      button.disabled=true;
      if(message)message.textContent='Saving mini-domain…';
      try{
        const response=await fetch('/api/v1/properties/'+form.dataset.property+'/mini-domain',{
          method:'PUT',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({mini_domain:value})
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Mini-domain could not be saved.';
          return;
        }
        if(message)message.textContent='Mini-domain saved.';
        const output=document.querySelector('[data-mini-domain-url]');
        const copy=document.querySelector('[data-copy-mini-domain]');
        if(output)output.textContent=data.data.mini_domain_url;
        if(copy)copy.dataset.url=data.data.mini_domain_url;
      }catch(_error){
        if(message)message.textContent='Mini-domain request could not complete.';
      }finally{
        button.disabled=false;
      }
    });
  }

  const copy=document.querySelector('[data-copy-mini-domain]');
  if(copy){
    copy.addEventListener('click',async function(){
      const value=copy.dataset.url||'';
      try{
        await navigator.clipboard.writeText(value);
        const original=copy.textContent;
        copy.textContent='Copied';
        setTimeout(function(){copy.textContent=original;},1000);
      }catch(_error){
        window.prompt('Copy hotel address:',value);
      }
    });
  }
})();


(function initDistributionManager(){
  document.querySelectorAll('[data-distribution-channel]').forEach(function(card){
    const button=card.querySelector('[data-channel-sync]');
    const message=card.querySelector('.form-message');
    if(!button)return;
    button.addEventListener('click',async function(){
      if(!window.confirm('Sync this property to '+button.dataset.channel.replaceAll('_',' ')+' now?'))return;
      button.disabled=true;
      if(message)message.textContent='Syncing property, rates, inventory and reservations…';
      try{
        const response=await fetch(
          '/api/v1/distribution/properties/'+button.dataset.property+'/'+button.dataset.channel+'/sync',
          {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}
        );
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Channel sync could not complete.';
          return;
        }
        const result=data.data||{};
        if(message)message.textContent=result.status==='active'?
          'Channel sync completed and was recorded.':
          'Channel sync completed with an error state. Check sync history.';
        setTimeout(function(){window.location.reload();},700);
      }catch(_error){
        if(message)message.textContent='Channel sync request could not complete.';
      }finally{
        button.disabled=false;
      }
    });
  });
})();


(function initDistributionStatusControls(){
  document.querySelectorAll('[data-channel-status]').forEach(function(button){
    const card=button.closest('[data-distribution-channel]');
    const message=card&&card.querySelector('.form-message');
    button.addEventListener('click',async function(){
      const target=button.dataset.status;
      const verb=target==='disconnected'?'pause':'resume';
      if(!window.confirm('Are you sure you want to '+verb+' automatic sync for this channel?'))return;
      button.disabled=true;
      if(message)message.textContent=target==='disconnected'?'Pausing automatic sync…':'Resuming automatic sync…';
      try{
        const response=await fetch('/api/v1/distribution/connections/'+button.dataset.connection+'/status',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({status:target})
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Channel status could not be changed.';
          return;
        }
        if(message)message.textContent=target==='disconnected'?
          'Automatic sync paused. Manual sync can resume it.':
          'Automatic sync resumed.';
        setTimeout(function(){window.location.reload();},600);
      }catch(_error){
        if(message)message.textContent='Channel status request could not complete.';
      }finally{
        button.disabled=false;
      }
    });
  });
})();


document.querySelectorAll('[data-physical-room-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const message=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    const raw=form.querySelector('[name="room_numbers"]').value||'';
    const roomNumbers=[...new Set(raw.split(/[\n,]+/).map(function(value){return value.trim();}).filter(Boolean))];
    if(!roomNumbers.length){message.textContent='Add at least one room number.';return;}
    submit.disabled=true;
    message.textContent='Adding room numbers…';
    try{
      const response=await fetch('/api/v1/room-types/'+form.dataset.room+'/physical-rooms',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          room_numbers:roomNumbers,
          floor:(form.querySelector('[name="floor"]').value||'').trim()||null
        })
      });
      const data=await response.json().catch(function(){return {};});
      if(!response.ok){
        message.textContent=(data.error&&data.error.message)||'Room numbers could not be added.';
        return;
      }
      window.location.reload();
    }catch(_error){
      message.textContent='Room numbers could not be added.';
    }finally{
      submit.disabled=false;
    }
  });
});

document.querySelectorAll('[data-physical-room]').forEach(function(row){
  const select=row.querySelector('[data-room-readiness-select]');
  const remove=row.querySelector('[data-physical-room-delete]');
  const message=row.querySelector('.form-message');

  if(select){
    select.dataset.current=select.value;
    select.addEventListener('change',async function(){
      const previous=select.dataset.current;
      select.disabled=true;
      if(message)message.textContent='Updating room…';
      try{
        const response=await fetch('/api/v1/physical-rooms/'+row.dataset.physicalRoom+'/readiness',{
          method:'PUT',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({status:select.value})
        });
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          select.value=previous;
          if(message)message.textContent=(data.error&&data.error.message)||'Room readiness could not be updated.';
          return;
        }
        select.dataset.current=select.value;
        window.location.reload();
      }catch(_error){
        select.value=previous;
        if(message)message.textContent='Room readiness could not be updated.';
      }finally{
        select.disabled=false;
      }
    });
  }

  if(remove){
    remove.addEventListener('click',async function(){
      if(!window.confirm('Remove this physical room number?'))return;
      remove.disabled=true;
      if(message)message.textContent='Removing room…';
      try{
        const response=await fetch('/api/v1/physical-rooms/'+row.dataset.physicalRoom,{method:'DELETE'});
        const data=await response.json().catch(function(){return {};});
        if(!response.ok){
          if(message)message.textContent=(data.error&&data.error.message)||'Room could not be removed.';
          remove.disabled=false;
          return;
        }
        row.remove();
      }catch(_error){
        if(message)message.textContent='Room could not be removed.';
        remove.disabled=false;
      }
    });
  }
});


document.querySelectorAll('[data-handover-form]').forEach(function(form){
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    const message=form.querySelector('.form-message');
    const submit=form.querySelector('button[type="submit"]');
    const data=Object.fromEntries(new FormData(form).entries());
    submit.disabled=true;
    message.textContent='Saving handover note…';
    try{
      const response=await fetch('/api/v1/partner/handover',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          property_id:data.property_id,
          priority:data.priority||'normal',
          note:(data.note||'').trim()
        })
      });
      const body=await response.json().catch(function(){return {};});
      if(!response.ok){
        message.textContent=(body.error&&body.error.message)||'Handover note could not be saved.';
        return;
      }
      window.location.reload();
    }catch(_error){
      message.textContent='Handover note could not be saved.';
    }finally{
      submit.disabled=false;
    }
  });
});

document.querySelectorAll('[data-handover-note]').forEach(function(row){
  const resolve=row.querySelector('[data-handover-resolve]');
  const message=row.querySelector('.form-message');
  if(!resolve)return;
  resolve.addEventListener('click',async function(){
    if(!window.confirm('Mark this handover note as resolved?'))return;
    resolve.disabled=true;
    if(message)message.textContent='Resolving…';
    try{
      const response=await fetch('/api/v1/partner/handover/'+row.dataset.handoverNote+'/resolve',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:'{}'
      });
      const body=await response.json().catch(function(){return {};});
      if(!response.ok){
        if(message)message.textContent=(body.error&&body.error.message)||'Handover note could not be resolved.';
        resolve.disabled=false;
        return;
      }
      row.remove();
    }catch(_error){
      if(message)message.textContent='Handover note could not be resolved.';
      resolve.disabled=false;
    }
  });
});


document.querySelectorAll('[data-front-desk-reservation-form]').forEach(function(form){
  const radios=[...form.querySelectorAll('[name="stay_option"]')];
  const quantity=form.querySelector('[name="quantity"]');
  const adults=form.querySelector('[name="adults"]');
  const children=form.querySelector('[name="children"]');
  const roomInput=form.querySelector('[name="room_type_id"]');
  const rateInput=form.querySelector('[name="rate_plan_id"]');
  const total=form.querySelector('[data-front-desk-total]');
  const message=form.querySelector('.form-message');
  const submit=form.querySelector('button[type="submit"]');

  function selectedOption(){
    return radios.find(function(radio){return radio.checked;})||radios[0];
  }

  function sync(){
    const option=selectedOption();
    if(!option)return;
    roomInput.value=option.dataset.room;
    rateInput.value=option.dataset.rate;
    const maxRooms=Math.max(1,Math.min(Number(option.dataset.available||1),10));
    quantity.max=String(maxRooms);
    if(Number(quantity.value)>maxRooms)quantity.value=String(maxRooms);
    const rooms=Math.max(1,Number(quantity.value||1));
    const adultMax=Math.max(1,Number(option.dataset.adults||1)*rooms);
    const childMax=Math.max(0,Number(option.dataset.children||0)*rooms);
    adults.max=String(adultMax);
    children.max=String(childMax);
    if(Number(adults.value)>adultMax)adults.value=String(adultMax);
    if(Number(children.value)>childMax)children.value=String(childMax);
    const stayTotal=(Number(option.dataset.price||0)*rooms)/100;
    total.textContent=(option.dataset.currency||'NGN')+' '+stayTotal.toFixed(2);
  }

  radios.forEach(function(radio){radio.addEventListener('change',sync);});
  quantity.addEventListener('input',sync);
  sync();

  form.addEventListener('submit',async function(event){
    event.preventDefault();
    sync();
    if(!form.reportValidity())return;
    if(!form.dataset.idempotencyKey){
      form.dataset.idempotencyKey='frontdesk-'+(
        window.crypto&&crypto.randomUUID ? crypto.randomUUID() : Date.now()+'-'+Math.random().toString(16).slice(2)
      );
    }
    const data=Object.fromEntries(new FormData(form).entries());
    submit.disabled=true;
    message.textContent='Confirming reservation…';
    try{
      const response=await fetch('/api/v1/partner/reservations',{
        method:'POST',
        headers:{
          'Content-Type':'application/json',
          'Idempotency-Key':form.dataset.idempotencyKey
        },
        body:JSON.stringify({
          property_id:data.property_id,
          room_type_id:data.room_type_id,
          rate_plan_id:data.rate_plan_id,
          check_in:data.check_in,
          check_out:data.check_out,
          quantity:Number(data.quantity),
          adults:Number(data.adults),
          children:Number(data.children),
          guest_name:(data.guest_name||'').trim(),
          guest_phone:(data.guest_phone||'').trim(),
          guest_email:(data.guest_email||'').trim()||null
        })
      });
      const body=await response.json().catch(function(){return {};});
      if(!response.ok){
        message.textContent=(body.error&&body.error.message)||'Reservation could not be created.';
        return;
      }
      const result=body.data||{};
      window.location.href=result.redirect_to||('/partner/reservations/'+result.reservation_id);
    }catch(_error){
      message.textContent='Reservation could not be created. You can retry safely.';
    }finally{
      submit.disabled=false;
    }
  });
});
