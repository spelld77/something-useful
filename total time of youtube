//유튜브에서 영상 개수와 썸네일 표시된 시간의 합을 구한다
//유튜브 동영상 탭에서 확인함
//개발자 도구 콘솔창에서 확인 가능
//viewTime()메소드 사용


//처음 입력할 때 실행
viewTime()

//****채널 전체시간 보기(밑으로 끝까지 로딩 필요)*****//
function viewTime(){
    var timeArray = getTimeArray();
    var videoNum = timeArray.length;
    var seconds = getSeconds(timeArray);

    //출력
    console.log('영상개수: ' + videoNum);
    printTime(seconds);
}


//방송시간 배열 구하기
function getTimeArray(){
    var timeClassElement = 'style-scope ytd-thumbnail-overlay-time-status-renderer'; //시간 요소있는 클래스 이름
    var rawTimeTag = document.getElementsByClassName(timeClassElement); // 시간아닌것도 포함된 모든 태그
    var realTimeTag = new Array(); //방송 시간의 문자열 배열

    //시간만 포함된 배열로 만들기
    for(let i=0; i<rawTimeTag.length; i++){ //htmlcollection
        var timeInfo = rawTimeTag[i].innerText.trim(); //시간정보
        if(timeInfo == ""){ //시간 정보 없으면 통과
            continue;
        }
        realTimeTag.push(timeInfo); //배열에 추가
    }
    return realTimeTag; //실제 방송시간 배열 리턴
}


//배열시간을 초(second)로 만들기
function getSeconds(array){
    var seconds = 0;
    for(let i=0; i<array.length; i++){
        var item = array[i];
        
        var length = item.length; //길이에 따라 구분
        switch (length) {
            case 4:
                seconds += parseInt(item.substring(0,1)) * 60 + parseInt(item.substring(2));
                break;
                
            case 5:
                seconds += parseInt(item.substring(0,2)) * 60 + parseInt(item.substring(3));
                break;

            case 7:
                seconds +=
                parseInt(item.substring(0,1)) * 3600 +
                parseInt(item.substring(2,4)) * 60 + parseInt(item.substring(5));
                break;

            case 8:
                seconds +=
                parseInt(item.substring(0,2)) * 3600 +
                parseInt(item.substring(3,5)) * 60 + parseInt(item.substring(6));
                break;

            default:
                console.log('Needs more case statement');
                break;
        }
    }
    return seconds;
}

//초(second)를 시간 분 초로 표시
function printTime(seconds){
    var hr =0;
    var min=0;
    var sec=0;
    var temp=0;

    hr = parseInt(seconds / 3600); //시(hour)
    temp = parseInt(seconds % 3600); //hour가 되지 못하는 나머진 seconds
    min = parseInt(temp / 60); //분
    sec = parseInt(temp % 60); //초

    console.log("총 시간: " + hr +"시간 " + min + "분 " + sec + "초");
}
