/* Mature calendar widget; dates are converted explicitly to Beijing midnight. */
let rangeCalendar;
const shortcutNames=['今天','昨天','本周','上周','本月','上月','今年','最近 24 小时','最近 7 天'];
const localDateString=(d)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
function openRangePicker(){
  $('draft-start').value=dateISO(state.start);
  $('draft-end').value=dateISO(state.end-1);
  $('range-error').textContent='';
  $('range-shortcuts').innerHTML=`<span>快捷范围</span>${shortcutNames.map(name=>`<button data-range-shortcut="${name}" class="${state.preset===name?'active':''}">${name}</button>`).join('')}`;
  $('range-dialog').showModal();
  if(rangeCalendar)rangeCalendar.destroy();
  rangeCalendar=flatpickr($('calendar-input'),{
    inline:true,appendTo:$('calendar-host'),mode:'range',dateFormat:'Y-m-d',
    locale:{...flatpickr.l10ns.zh,firstDayOfWeek:1},disableMobile:true,
    showMonths:window.innerWidth>760?2:1,maxDate:'2026-10-12',
    defaultDate:[$('draft-start').value,$('draft-end').value],
    onChange(dates){
      $('draft-start').value=dates[0]?localDateString(dates[0]):'';
      $('draft-end').value=dates[1]?localDateString(dates[1]):'';
      $('range-error').textContent='';
    }
  });
  const end=new Date($('draft-end').value+'T12:00:00');
  rangeCalendar.jumpToDate(window.innerWidth>760?new Date(end.getFullYear(),end.getMonth()-1,1):end);
}
$('range-trigger').onclick=openRangePicker;
$('range-close').onclick=$('range-cancel').onclick=()=>$('range-dialog').close();
$('range-shortcuts').onclick=e=>{const button=e.target.closest('[data-range-shortcut]');if(button){preset(button.dataset.rangeShortcut);$('range-dialog').close();}};
for(const id of ['draft-start','draft-end'])$(id).addEventListener('change',()=>{
  rangeCalendar.setDate([$('draft-start').value,$('draft-end').value].filter(Boolean),false);
  $('range-error').textContent='';
});
$('range-apply').onclick=()=>{
  const start=Date.parse($('draft-start').value+'T00:00:00+08:00');
  const inclusiveEnd=Date.parse($('draft-end').value+'T00:00:00+08:00')+dayMs;
  const end=Math.min(asOf,inclusiveEnd);
  if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end){$('range-error').textContent='请选择完整范围，结束日期不能早于开始日期。';return;}
  if(inclusiveEnd>asOf+dayMs){$('range-error').textContent='结束日期不能晚于演示日期 10 月 12 日。';return;}
  rememberNavigation();delete state.drillStart;delete state.drillEnd;state.start=start;state.end=end;state.preset='自定义';state.pageNum=1;
  render();$('range-dialog').close();
};
$('range-dialog').addEventListener('click',e=>{if(e.target===$('range-dialog')){const r=$('range-dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('range-dialog').close();}});
